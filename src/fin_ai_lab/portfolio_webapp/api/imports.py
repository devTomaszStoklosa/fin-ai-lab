"""Broker file import: XTB/known formats, Bossa, and the LLM-proposed parser config."""

import zipfile
from collections.abc import Callable
from datetime import date as date_type
from uuid import UUID

import duckdb
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import ValidationError

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.api.common import (
    get_db,
    resolve_account_type,
    to_position_out,
    to_snapshot_out,
)
from fin_ai_lab.portfolio_webapp.api.defaults import MODEL
from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.bossa_financial import (
    FinancialHistory,
    is_financial_history,
    parse_financial_history,
)
from fin_ai_lab.portfolio_webapp.cash_operations import (
    CashHistory,
    CashOperationsError,
    extract_xtb_cash_operations,
)
from fin_ai_lab.portfolio_webapp.closed_lots import ClosedLotsHistory, extract_xtb_closed_lots
from fin_ai_lab.portfolio_webapp.lots import (
    OpenLot,
    extract_xtb_open_lots,
    lots_matching_quantity,
)
from fin_ai_lab.portfolio_webapp.repository import PortfolioRow
from fin_ai_lab.portfolio_webapp.schemas import (
    ImportResponse,
    PositionPreviewOut,
    ProposePreview,
)
from fin_ai_lab.portfolio_webapp.traded_instruments_builder import identify_missing_listings
from fin_ai_lab.portfolio_xray.canonical import AccountType, Position
from fin_ai_lab.portfolio_xray.identification.openfigi import OpenFigiClient
from fin_ai_lab.portfolio_xray.ledger import BossaTransaction, parse_bossa_csv
from fin_ai_lab.portfolio_xray.parsers.config import ParserConfig
from fin_ai_lab.portfolio_xray.parsers.correction import (
    CorrectionLoopError,
    propose_and_validate_config,
)
from fin_ai_lab.portfolio_xray.parsers.reader import read_xlsx_sheets
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry
from fin_ai_lab.portfolio_xray.privacy.injection import flag_suspicious_cells
from fin_ai_lab.portfolio_xray.service import build_bossa_import_result, import_file


def _resolve_portfolio_and_date(
    connection: duckdb.DuckDBPyConnection, portfolio_id: UUID, valuation_date: str
) -> tuple[PortfolioRow, date_type]:
    portfolio = repository.get_portfolio(connection, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    try:
        parsed_date = date_type.fromisoformat(valuation_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"errors": [str(exc)], "warnings": []}) from exc

    return portfolio, parsed_date


async def _import_and_persist(
    connection: duckdb.DuckDBPyConnection,
    *,
    portfolio_id: UUID,
    portfolio: PortfolioRow,
    file_bytes: bytes,
    valuation_date: date_type,
    account_type: AccountType,
    registry: ParserRegistry,
    openfigi_client: OpenFigiClient | None,
    quote_currency_fetcher: Callable[[str], str | None],
) -> ImportResponse:
    """Shared by /import and /import/approve -- once a registry that already
    recognizes the file's format is in hand (built-in for /import, just
    saved for /approve), the rest (parse, persist snapshot + positions) is
    identical."""
    try:
        result = await import_file(
            file_bytes,
            valuation_date=valuation_date,
            account_type=account_type,
            market_currency="PLN",
            registry=registry,
            openfigi_client=openfigi_client,
            quote_currency_fetcher=quote_currency_fetcher,
        )
    except (zipfile.BadZipFile, InvalidFileException) as exc:
        # A CLI user already picked a file they know is an XTB export; a
        # browser upload has no such guarantee, so unlike the CLI (which
        # lets this propagate) the API turns "not actually a spreadsheet"
        # into the same clean error shape as an unmatched-but-valid one.
        raise HTTPException(
            status_code=422,
            detail={"errors": [f"Unreadable file: {exc}"], "warnings": []},
        ) from exc

    if result.errors:
        raise HTTPException(
            status_code=422,
            detail={"errors": result.errors, "warnings": result.warnings},
        )

    # The snapshot's broker is what was actually parsed, not the portfolio's
    # own broker label from S1 -- those can drift (e.g. mislabeled at
    # creation). Falls back to the portfolio's label only when a "known
    # format" import somehow yields zero positions.
    broker = result.positions[0].broker if result.positions else (portfolio[2] or "unknown")
    # Read before anything is written: a failure here must not leave a
    # snapshot without its cash operations.
    history, cash_warnings = _read_cash_history(file_bytes)
    closed_lots, lots_warnings = _read_closed_lots(file_bytes)
    response = _persist_snapshot_and_positions(
        connection,
        portfolio_id=portfolio_id,
        broker=broker,
        valuation_date=valuation_date,
        positions=result.positions,
        warnings=result.warnings + cash_warnings + lots_warnings,
        lots=_extract_lots_best_effort(file_bytes, registry),
    )
    if history is not None:
        response.cash_operations_added = repository.insert_cash_operations(
            connection, portfolio_id=portfolio_id, operations=history.operations
        )
    if closed_lots is not None:
        response.closed_lots_added = repository.insert_closed_lots(
            connection, portfolio_id=portfolio_id, lots=closed_lots.lots
        )
    return response


def _financial_history_warnings(history: FinancialHistory) -> list[str]:
    """What the Bossa financial history could not use -- an unknown title
    would otherwise silently leave money out of the investment result, and an
    unreadable settlement row a trade out of the holdings."""
    warnings = [
        f"Historia finansowa: nieznany tytuł operacji „{title}” — pominięty."
        for title in history.unknown_titles
    ]
    if history.unreadable_rows:
        warnings.append(
            f"Historia finansowa: {history.unreadable_rows} wierszy nie do odczytania — pominięte."
        )
    return warnings


def _read_closed_lots(file_bytes: bytes) -> tuple[ClosedLotsHistory | None, list[str]]:
    """The XTB Closed Positions sheet, with a warning for every lot it could
    not use: a lot left out of the holdings history understates the days it
    was held."""
    try:
        history = extract_xtb_closed_lots(file_bytes)
    except CashOperationsError as exc:
        return None, [f"Closed Positions nie zaimportowane: {exc}"]
    if history is None:
        return None, []
    warnings: list[str] = []
    if history.skipped_short:
        warnings.append(
            f"Closed Positions: {history.skipped_short} pozycji krótkich (SELL) pominiętych "
            "w historii wartości."
        )
    if history.skipped_unpriced:
        warnings.append(
            f"Closed Positions: {history.skipped_unpriced} pozycji bez wartości zakupu lub "
            "sprzedaży (CFD, krypto) pominiętych w historii wartości."
        )
    if history.unreadable_rows:
        warnings.append(
            f"Closed Positions: {history.unreadable_rows} wierszy bez czasu otwarcia lub "
            "zamknięcia — pominięte."
        )
    return history, warnings


def _read_cash_history(file_bytes: bytes) -> tuple[CashHistory | None, list[str]]:
    """The XTB Cash Operations sheet, with a warning for everything it could
    not use -- an unknown type would otherwise silently leave money out of
    the investment result."""
    try:
        history = extract_xtb_cash_operations(file_bytes)
    except CashOperationsError as exc:
        return None, [f"Cash Operations nie zaimportowane: {exc}"]
    if history is None:
        return None, []
    warnings = [
        f"Cash Operations: nieznany typ operacji „{op_type}” — pominięty w wyniku inwestycji."
        for op_type in history.unknown_types
    ]
    if history.unreadable_rows:
        warnings.append(
            f"Cash Operations: {history.unreadable_rows} wierszy bez ID, daty lub kwoty "
            "— pominięte."
        )
    return history, warnings


def _extract_lots_best_effort(file_bytes: bytes, registry: ParserRegistry) -> list[OpenLot]:
    # Lots only refine the value history's start (S10) -- a file P1 just
    # imported fine must never fail on this extra read, so any surprise in
    # the detail rows means "no lots", not a 500.
    try:
        return extract_xtb_open_lots(file_bytes, registry)
    except Exception:
        return []


def _persist_snapshot_and_positions(
    connection: duckdb.DuckDBPyConnection,
    *,
    portfolio_id: UUID,
    broker: str,
    valuation_date: date_type,
    positions: list[Position],
    warnings: list[str],
    lots: list[OpenLot] | None = None,
) -> ImportResponse:
    """Shared by every import path (XTB, Bossa, and any future propose/approve
    broker) once it has a resolved position list ready to store -- freshly
    imported, so already "now", no live-refresh attempt needed."""
    snapshot_row = repository.create_snapshot(
        connection, portfolio_id=portfolio_id, broker=broker, valuation_date=valuation_date
    )
    repository.insert_positions(connection, snapshot_id=snapshot_row[0], positions=positions)
    position_rows = repository.list_positions(connection, snapshot_row[0])
    if lots:
        # row[6] is symbol, row[8] quantity -- XTB lots are keyed by ticker,
        # the same column P1 maps to Position.symbol.
        quantity_by_symbol = {row[6]: row[8] for row in position_rows if row[6] is not None}
        matched = lots_matching_quantity(lots, quantity_by_symbol)
        for row in position_rows:
            if row[6] in matched:
                repository.insert_lots(connection, position_id=row[0], lots=matched[row[6]])
    return ImportResponse(
        snapshot=to_snapshot_out(snapshot_row, [to_position_out(p) for p in position_rows]),
        warnings=warnings,
    )


def _flag_bossa_injection_warnings(transactions: list[BossaTransaction]) -> list[str]:
    # Only instrument_name is genuine freeform text in a Bossa row (isin and
    # currency are fixed-format codes) -- and it's exactly the field that
    # survives into Position.instrument_name and, from there, into report
    # prompts (REQ-004). Bossa's import had no such scan at all before this.
    return flag_suspicious_cells([(t.instrument_name,) for t in transactions])


def _flag_injection_warnings(sheets: dict[str, list[tuple[object, ...]]]) -> list[str]:
    # Mirrors service.py's own (module-private) _flag_all_sheets exactly --
    # duplicated rather than imported, since portfolio_webapp may only reach
    # into P1's public functions (docs/ARCHITECTURE.md rule 6), and this is
    # five lines built entirely from the public flag_suspicious_cells.
    warnings: list[str] = []
    for sheet_name, rows in sheets.items():
        for flag in flag_suspicious_cells(rows):
            warnings.append(f"{sheet_name}, {flag}")
    return warnings


def _to_position_preview(position: Position) -> PositionPreviewOut:
    return PositionPreviewOut(
        instrument_name=position.instrument_name,
        isin=position.isin,
        symbol=position.symbol,
        asset_class=position.asset_class,
        quantity=position.quantity,
        avg_cost=position.avg_cost,
        cost_currency=position.cost_currency,
        market_value=position.market_value,
        market_currency=position.market_currency,
    )


def build_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/portfolios/{portfolio_id}/import",
        response_model=ImportResponse,
        status_code=201,
    )
    async def import_portfolio_file(
        portfolio_id: UUID,
        file: UploadFile = File(...),
        valuation_date: str = Form(...),
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> ImportResponse:
        portfolio, parsed_date = _resolve_portfolio_and_date(
            connection, portfolio_id, valuation_date
        )
        return await _import_and_persist(
            connection,
            portfolio_id=portfolio_id,
            portfolio=portfolio,
            file_bytes=await file.read(),
            valuation_date=parsed_date,
            account_type=resolve_account_type(portfolio),
            registry=deps.parser_registry_factory(),
            openfigi_client=deps.openfigi_client_factory(),
            quote_currency_fetcher=deps.quote_currency_fetcher,
        )

    @router.post(
        "/api/portfolios/{portfolio_id}/import/bossa",
        response_model=ImportResponse,
        status_code=201,
    )
    async def import_bossa_portfolio_file(
        portfolio_id: UUID,
        file: UploadFile = File(...),
        valuation_date: str = Form(...),
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> ImportResponse:
        # Bossa has two known export shapes -- a transaction ledger (hisPW)
        # and the financial history (#246) -- both turning into the same
        # stored trades, neither a position snapshot: no propose/approve
        # step, unlike XTB and any other row-mapped broker.
        portfolio, parsed_date = _resolve_portfolio_and_date(
            connection, portfolio_id, valuation_date
        )

        file_bytes = await file.read()
        history: FinancialHistory | None = None
        try:
            if is_financial_history(file_bytes):
                history = parse_financial_history(file_bytes)
                new_transactions = history.transactions
            else:
                new_transactions = parse_bossa_csv(file_bytes)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail={"errors": [str(exc)], "warnings": []}
            ) from exc

        injection_warnings = _flag_bossa_injection_warnings(new_transactions)
        cash_operations_added: int | None = None
        if history is not None:
            repository.insert_financial_history_trades(
                connection,
                portfolio_id=portfolio_id,
                broker="bossa",
                transactions=new_transactions,
            )
            cash_operations_added = repository.insert_cash_operations(
                connection, portfolio_id=portfolio_id, operations=history.operations
            )
            injection_warnings = injection_warnings + _financial_history_warnings(history)
        else:
            repository.insert_transactions(
                connection,
                portfolio_id=portfolio_id,
                broker="bossa",
                transactions=new_transactions,
            )
        # Positions always come from replaying the complete stored ledger,
        # never from just the file that was just uploaded (REQ-021) -- an
        # earlier import's holdings must not disappear just because the
        # latest file only covers a later date range.
        all_transactions = repository.list_transactions(connection, portfolio_id)
        openfigi_client = deps.openfigi_client_factory()
        # Every traded ISIN, sold ones included, gets the listing the value
        # history prices it by (#277) -- held positions alone would leave
        # everything sold at a constant value.
        if openfigi_client is not None:
            injection_warnings = injection_warnings + await identify_missing_listings(
                connection, all_transactions, openfigi_client, deps.quote_currency_fetcher
            )

        result = await build_bossa_import_result(
            all_transactions,
            account_type=resolve_account_type(portfolio),
            valuation_date=parsed_date,
            openfigi_client=openfigi_client,
            # Bossa trades on the Warsaw Stock Exchange; "PW" is OpenFIGI's
            # real exchange code for it (same one already used for XTB's own
            # Polish listings), not a guess.
            broker_market="PW",
            quote_currency_fetcher=deps.quote_currency_fetcher,
            fx_client=deps.fx_client_factory(),
        )
        if result.errors:
            raise HTTPException(
                status_code=422,
                detail={"errors": result.errors, "warnings": result.warnings + injection_warnings},
            )

        response = _persist_snapshot_and_positions(
            connection,
            portfolio_id=portfolio_id,
            broker="bossa",
            valuation_date=parsed_date,
            positions=result.positions,
            warnings=result.warnings + injection_warnings,
        )
        response.cash_operations_added = cash_operations_added
        return response

    @router.post(
        "/api/portfolios/{portfolio_id}/import/propose",
        response_model=ProposePreview,
    )
    async def propose_import_config(
        portfolio_id: UUID,
        request: Request,
        file: UploadFile = File(...),
        broker: str = Form(...),
        valuation_date: str = Form(...),
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> ProposePreview:
        portfolio, parsed_date = _resolve_portfolio_and_date(
            connection, portfolio_id, valuation_date
        )
        account_type = resolve_account_type(portfolio)

        try:
            sheets = read_xlsx_sheets(await file.read())
        except (zipfile.BadZipFile, InvalidFileException) as exc:
            raise HTTPException(
                status_code=422,
                detail={"errors": [f"Unreadable file: {exc}"], "warnings": []},
            ) from exc

        warnings = _flag_injection_warnings(sheets)

        try:
            config, positions = await propose_and_validate_config(
                deps.llm_client_factory(),
                request.app.state.prompt_registry,
                MODEL,
                sheets,
                broker=broker,
                version=deps.parser_registry_factory().next_version(broker),
                account_type=account_type,
                market_currency="PLN",
                valuation_date=parsed_date,
            )
        except CorrectionLoopError as exc:
            raise HTTPException(
                status_code=422, detail={"errors": [str(exc)], "warnings": warnings}
            ) from exc

        # Nothing saved yet -- no registry.save(), no snapshot, no positions
        # in the database. That only happens on /approve.
        return ProposePreview(
            config=config,
            positions=[_to_position_preview(p) for p in positions],
            warnings=warnings,
        )

    @router.post(
        "/api/portfolios/{portfolio_id}/import/approve",
        response_model=ImportResponse,
        status_code=201,
    )
    async def approve_import_config(
        portfolio_id: UUID,
        file: UploadFile = File(...),
        config: str = Form(...),
        valuation_date: str = Form(...),
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> ImportResponse:
        portfolio, parsed_date = _resolve_portfolio_and_date(
            connection, portfolio_id, valuation_date
        )

        try:
            parsed_config = ParserConfig.model_validate_json(config)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail={"errors": [str(exc)], "warnings": []}
            ) from exc

        # Only now does the config become permanent -- registry.save() never
        # overwrites an existing version file, so this is additive even if
        # called more than once for the same proposal.
        registry = deps.parser_registry_factory()
        registry.save(parsed_config)

        return await _import_and_persist(
            connection,
            portfolio_id=portfolio_id,
            portfolio=portfolio,
            file_bytes=await file.read(),
            valuation_date=parsed_date,
            account_type=resolve_account_type(portfolio),
            registry=registry,
            openfigi_client=deps.openfigi_client_factory(),
            quote_currency_fetcher=deps.quote_currency_fetcher,
        )

    return router
