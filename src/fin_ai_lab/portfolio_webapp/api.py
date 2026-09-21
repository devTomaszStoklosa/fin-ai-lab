import zipfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date as date_type
from pathlib import Path
from typing import get_args
from uuid import UUID

import duckdb
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import ValidationError

from fin_ai_lab.core.config import Settings
from fin_ai_lab.core.llm.client import GeminiLlmClient, LlmClient
from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.portfolio_webapp import db, repository
from fin_ai_lab.portfolio_webapp.repository import PortfolioRow, PositionRow, SnapshotRow
from fin_ai_lab.portfolio_webapp.schemas import (
    ImportResponse,
    PortfolioCreate,
    PortfolioOut,
    PositionOut,
    PositionPreviewOut,
    ProposePreview,
    SnapshotOut,
)
from fin_ai_lab.portfolio_xray.canonical import AccountType, Position
from fin_ai_lab.portfolio_xray.identification.openfigi import OpenFigiClient
from fin_ai_lab.portfolio_xray.parsers.config import ParserConfig
from fin_ai_lab.portfolio_xray.parsers.correction import (
    CorrectionLoopError,
    propose_and_validate_config,
)
from fin_ai_lab.portfolio_xray.parsers.reader import read_xlsx_sheets
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry
from fin_ai_lab.portfolio_xray.privacy.injection import flag_suspicious_cells
from fin_ai_lab.portfolio_xray.service import import_file

# Same default as the CLI (cli.py's `import` command) -- not exposed as a
# web UI option, this tool doesn't need model choice as a user-facing knob.
MODEL = "gemini-3.6-flash"
# cwd-relative, same as cli.py's PORTFOLIO_PROMPTS_DIR -- both are always
# launched via `uv run` from the repo root. Not imported from cli.py:
# portfolio_webapp may only depend on core and portfolio_xray.service
# (docs/ARCHITECTURE.md rule 6), not on the CLI module.
PORTFOLIO_PROMPTS_DIR = Path("src/fin_ai_lab/portfolio_xray/parsers/prompts")


def _default_llm_client() -> LlmClient:
    settings = Settings()
    if settings.gemini_api_key:
        return GeminiLlmClient(api_key=settings.gemini_api_key)
    return FakeLlmClient({})


def create_app(
    db_path: Path = db.DEFAULT_DB_PATH,
    # Injected rather than constructed inline (SOLID/D): production gets a
    # real, network-calling client by default; tests substitute `lambda: None`
    # so importing a synthetic file never depends on the network, the same
    # guarantee P1's own tests already rely on for `openfigi_client=None`.
    openfigi_client_factory: Callable[[], OpenFigiClient | None] = OpenFigiClient,
    # Same reasoning as openfigi_client_factory: tests substitute a
    # FakeLlmClient with canned responses instead of calling Gemini.
    llm_client_factory: Callable[[], LlmClient] = _default_llm_client,
    # Same reasoning again: ParserRegistry() defaults to the real, checked-in
    # parsers/ directory -- fine for production (CLI and web app are meant
    # to share it), but /import/approve calls registry.save(), so a test
    # exercising it must inject a ParserRegistry(parsers_dir=tmp_path) or it
    # would write a real YAML file into the source tree.
    parser_registry_factory: Callable[[], ParserRegistry] = ParserRegistry,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = db.connect(db_path)
        # Loaded once, unlike ParserRegistry: prompts are static app
        # configuration, not something that needs to reflect a change made
        # by the previous request.
        prompt_registry = PromptRegistry()
        prompt_registry.load_dir(PORTFOLIO_PROMPTS_DIR)
        app.state.prompt_registry = prompt_registry
        yield
        app.state.db.close()

    app = FastAPI(title="Portfel", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/portfolios", response_model=list[PortfolioOut])
    def list_portfolios(
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> list[PortfolioOut]:
        return [_to_portfolio_out(row) for row in repository.list_portfolios(connection)]

    @app.post("/api/portfolios", response_model=PortfolioOut, status_code=201)
    def create_portfolio(
        payload: PortfolioCreate,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> PortfolioOut:
        row = repository.create_portfolio(
            connection,
            name=payload.name,
            broker=payload.broker,
            account_type=payload.account_type,
        )
        return _to_portfolio_out(row)

    @app.post(
        "/api/portfolios/{portfolio_id}/import",
        response_model=ImportResponse,
        status_code=201,
    )
    async def import_portfolio_file(
        portfolio_id: UUID,
        file: UploadFile = File(...),
        valuation_date: str = Form(...),
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
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
            account_type=_resolve_account_type(portfolio),
            registry=parser_registry_factory(),
            openfigi_client=openfigi_client_factory(),
        )

    @app.post(
        "/api/portfolios/{portfolio_id}/import/propose",
        response_model=ProposePreview,
    )
    async def propose_import_config(
        portfolio_id: UUID,
        file: UploadFile = File(...),
        broker: str = Form(...),
        valuation_date: str = Form(...),
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> ProposePreview:
        portfolio, parsed_date = _resolve_portfolio_and_date(
            connection, portfolio_id, valuation_date
        )
        account_type = _resolve_account_type(portfolio)

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
                llm_client_factory(),
                app.state.prompt_registry,
                MODEL,
                sheets,
                broker=broker,
                version=parser_registry_factory().next_version(broker),
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

    @app.post(
        "/api/portfolios/{portfolio_id}/import/approve",
        response_model=ImportResponse,
        status_code=201,
    )
    async def approve_import_config(
        portfolio_id: UUID,
        file: UploadFile = File(...),
        config: str = Form(...),
        valuation_date: str = Form(...),
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
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
        registry = parser_registry_factory()
        registry.save(parsed_config)

        return await _import_and_persist(
            connection,
            portfolio_id=portfolio_id,
            portfolio=portfolio,
            file_bytes=await file.read(),
            valuation_date=parsed_date,
            account_type=_resolve_account_type(portfolio),
            registry=registry,
            openfigi_client=openfigi_client_factory(),
        )

    @app.get("/api/portfolios/{portfolio_id}/snapshots", response_model=list[SnapshotOut])
    def list_snapshots(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> list[SnapshotOut]:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        return [
            _to_snapshot_out(row, repository.list_positions(connection, row[0]))
            for row in repository.list_snapshots(connection, portfolio_id)
        ]

    return app


def _resolve_portfolio_and_date(
    connection: duckdb.DuckDBPyConnection, portfolio_id: UUID, valuation_date: str
) -> tuple[PortfolioRow, date_type]:
    portfolio = repository.get_portfolio(connection, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    try:
        parsed_date = date_type.fromisoformat(valuation_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail={"errors": [str(exc)], "warnings": []}
        ) from exc

    return portfolio, parsed_date


def _resolve_account_type(portfolio: PortfolioRow) -> str:
    # portfolio[3] is account_type, stored free-text at creation time (S1);
    # a value outside P1's canonical AccountType would otherwise fail deep
    # inside Position construction with a raw ValidationError.
    account_type = portfolio[3]
    if account_type not in get_args(AccountType):
        return "regular"
    return account_type


async def _import_and_persist(
    connection: duckdb.DuckDBPyConnection,
    *,
    portfolio_id: UUID,
    portfolio: PortfolioRow,
    file_bytes: bytes,
    valuation_date: date_type,
    account_type: str,
    registry: ParserRegistry,
    openfigi_client: OpenFigiClient | None,
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
    snapshot_row = repository.create_snapshot(
        connection, portfolio_id=portfolio_id, broker=broker, valuation_date=valuation_date
    )
    repository.insert_positions(connection, snapshot_id=snapshot_row[0], positions=result.positions)
    position_rows = repository.list_positions(connection, snapshot_row[0])

    return ImportResponse(
        snapshot=_to_snapshot_out(snapshot_row, position_rows),
        warnings=result.warnings,
    )


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


def _get_db(request: Request) -> duckdb.DuckDBPyConnection:
    return request.app.state.db


def _to_portfolio_out(row: PortfolioRow) -> PortfolioOut:
    id_, name, broker, account_type, created_at = row
    return PortfolioOut(
        id=id_, name=name, broker=broker, account_type=account_type, created_at=created_at
    )


def _to_position_out(row: PositionRow) -> PositionOut:
    (
        id_,
        _snapshot_id,
        broker,
        account_type,
        instrument_name,
        isin,
        symbol,
        asset_class,
        quantity,
        avg_cost,
        cost_currency,
        market_value,
        market_currency,
        valuation_date,
        resolution_status,
        figi,
        ticker,
        exchange_code,
        identification_rule,
    ) = row
    return PositionOut(
        id=id_,
        broker=broker,
        account_type=account_type,
        instrument_name=instrument_name,
        isin=isin,
        symbol=symbol,
        asset_class=asset_class,
        quantity=quantity,
        avg_cost=avg_cost,
        cost_currency=cost_currency,
        market_value=market_value,
        market_currency=market_currency,
        valuation_date=valuation_date,
        resolution_status=resolution_status,
        figi=figi,
        ticker=ticker,
        exchange_code=exchange_code,
        identification_rule=identification_rule,
    )


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


def _to_snapshot_out(row: SnapshotRow, position_rows: list[PositionRow]) -> SnapshotOut:
    id_, portfolio_id, broker, valuation_date, imported_at, date_min, date_max = row
    return SnapshotOut(
        id=id_,
        portfolio_id=portfolio_id,
        broker=broker,
        valuation_date=valuation_date,
        imported_at=imported_at,
        source_file_date_min=date_min,
        source_file_date_max=date_max,
        positions=[_to_position_out(p) for p in position_rows],
    )
