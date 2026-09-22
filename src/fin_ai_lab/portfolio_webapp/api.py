import asyncio
import zipfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date as date_type
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import get_args
from uuid import UUID

import duckdb
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from google.genai import errors as genai_errors
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import ValidationError

from fin_ai_lab.core.config import Settings
from fin_ai_lab.core.llm.client import GeminiLlmClient, LlmClient
from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.portfolio_webapp import db, repository
from fin_ai_lab.portfolio_webapp.aggregators import (
    Aggregator,
    CycleError,
    instrument_key,
    resolve_value,
    validate_no_cycle,
)
from fin_ai_lab.portfolio_webapp.repository import PortfolioRow, PositionRow, SnapshotRow
from fin_ai_lab.portfolio_webapp.schemas import (
    AggregatorCreate,
    AggregatorOut,
    ImportResponse,
    MetricsOut,
    PortfolioCreate,
    PortfolioOut,
    PositionCreate,
    PositionOut,
    PositionPreviewOut,
    PositionUpdate,
    ProposePreview,
    ReportOut,
    SnapshotOut,
)
from fin_ai_lab.portfolio_xray.canonical import AccountType, Position
from fin_ai_lab.portfolio_xray.identification.openfigi import OpenFigiClient
from fin_ai_lab.portfolio_xray.metrics.fx import NbpFxClient, convert_to_base_currency
from fin_ai_lab.portfolio_xray.metrics.price_history import (
    fetch_quote_currency,
    price_change_ratio,
    to_yahoo_ticker,
)
from fin_ai_lab.portfolio_xray.metrics.weights import compute_weights
from fin_ai_lab.portfolio_xray.parsers.config import ParserConfig
from fin_ai_lab.portfolio_xray.parsers.correction import (
    CorrectionLoopError,
    propose_and_validate_config,
)
from fin_ai_lab.portfolio_xray.parsers.reader import read_xlsx_sheets
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry
from fin_ai_lab.portfolio_xray.privacy.injection import flag_suspicious_cells
from fin_ai_lab.portfolio_xray.report.builder import ReportRejectedError, build_report
from fin_ai_lab.portfolio_xray.report.models import InstrumentMetadata, MetricsJson
from fin_ai_lab.portfolio_xray.sectors.classifier import classify_sector
from fin_ai_lab.portfolio_xray.service import import_file

BASE_CURRENCY = "PLN"  # matches canonical.Portfolio.base_currency (Literal["PLN"])

# Same default as the CLI (cli.py's `import` command) -- not exposed as a
# web UI option, this tool doesn't need model choice as a user-facing knob.
MODEL = "gemini-3.6-flash"
# cwd-relative, same as cli.py's own prompt dirs -- both are always launched
# via `uv run` from the repo root. Not imported from cli.py: portfolio_webapp
# may only depend on core and portfolio_xray.service (docs/ARCHITECTURE.md
# rule 6), not on the CLI module.
PORTFOLIO_PROMPTS_DIR = Path("src/fin_ai_lab/portfolio_xray/parsers/prompts")
REPORT_PROMPTS_DIR = Path("src/fin_ai_lab/portfolio_xray/report/prompts")
SECTOR_PROMPTS_DIR = Path("src/fin_ai_lab/portfolio_xray/sectors/prompts")


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
    # Same reasoning as openfigi_client_factory -- NbpFxClient hits a real
    # HTTP API. PLN short-circuits without any network call (fx.py's
    # mid_rate), which is all every position in this app has today, but the
    # factory keeps the DI pattern consistent with the app's other clients.
    fx_client_factory: Callable[[], NbpFxClient] = NbpFxClient,
    # Not a client-factory like the others -- price_change_ratio is already
    # a plain function (P1 has no class here). Tests substitute a fake
    # returning canned ratios instead of calling yfinance.
    price_ratio_fetcher: Callable[[str, date_type], Decimal | None] = price_change_ratio,
    # Same reasoning as price_ratio_fetcher -- a plain function, tests
    # substitute a fake instead of calling yfinance.
    quote_currency_fetcher: Callable[[str], str | None] = fetch_quote_currency,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = db.connect(db_path)
        # Loaded once, unlike ParserRegistry: prompts are static app
        # configuration, not something that needs to reflect a change made
        # by the previous request. Three directories, one registry: prompt
        # ids don't collide across them (propose_config vs. narrative vs.
        # classify_sector), so load_dir is safe to call repeatedly.
        prompt_registry = PromptRegistry()
        prompt_registry.load_dir(PORTFOLIO_PROMPTS_DIR)
        prompt_registry.load_dir(REPORT_PROMPTS_DIR)
        prompt_registry.load_dir(SECTOR_PROMPTS_DIR)
        app.state.prompt_registry = prompt_registry
        # One lock per portfolio (02-spec.md edge case): a second "generuj"
        # while the first is still running waits for it instead of starting
        # a parallel LLM call for the same report.
        app.state.report_locks: dict[UUID, asyncio.Lock] = {}
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
            quote_currency_fetcher=quote_currency_fetcher,
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
            quote_currency_fetcher=quote_currency_fetcher,
        )

    @app.get("/api/portfolios/{portfolio_id}/snapshots", response_model=list[SnapshotOut])
    async def list_snapshots(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> list[SnapshotOut]:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        result: list[SnapshotOut] = []
        for index, row in enumerate(repository.list_snapshots(connection, portfolio_id)):
            position_rows = repository.list_positions(connection, row[0])
            # Only the latest snapshot (index 0) represents "now" in the UI
            # -- older ones are history (S7) and keep showing what they
            # showed at import time, so only this one's positions get a
            # live-refreshed value (issue #190).
            if index == 0:
                positions = [
                    await _to_position_out_with_live_value(p, price_ratio_fetcher)
                    for p in position_rows
                ]
            else:
                positions = [_to_position_out(p) for p in position_rows]
            result.append(_to_snapshot_out(row, positions))
        return result

    @app.get("/api/portfolios/{portfolio_id}/positions", response_model=list[PositionOut])
    def list_manual_positions(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> list[PositionOut]:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        snapshot = repository.find_manual_snapshot(connection, portfolio_id)
        if snapshot is None:
            return []
        return [_to_position_out(row) for row in repository.list_positions(connection, snapshot[0])]

    @app.post(
        "/api/portfolios/{portfolio_id}/positions", response_model=PositionOut, status_code=201
    )
    async def create_manual_position(
        portfolio_id: UUID,
        payload: PositionCreate,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> PositionOut:
        portfolio = repository.get_portfolio(connection, portfolio_id)
        if portfolio is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        # Valued at cost on creation (the owner just bought it, no other
        # price is known yet) -- editable to a real current value afterwards
        # via PUT, which is where market_value stops being auto-derived.
        position = await _build_manual_position(
            payload,
            account_type=_resolve_account_type(portfolio),
            market_value=payload.quantity * payload.avg_cost,
            openfigi_client=openfigi_client_factory(),
            quote_currency_fetcher=quote_currency_fetcher,
        )
        snapshot = repository.get_or_create_manual_snapshot(connection, portfolio_id)
        row = repository.insert_position(connection, snapshot_id=snapshot[0], position=position)
        return _to_position_out(row)

    @app.put("/api/portfolios/{portfolio_id}/positions/{position_id}", response_model=PositionOut)
    async def update_manual_position(
        portfolio_id: UUID,
        position_id: UUID,
        payload: PositionUpdate,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> PositionOut:
        portfolio = _require_manual_position(connection, portfolio_id, position_id)

        position = await _build_manual_position(
            payload,
            account_type=_resolve_account_type(portfolio),
            market_value=payload.market_value,
            openfigi_client=openfigi_client_factory(),
            quote_currency_fetcher=quote_currency_fetcher,
        )
        row = repository.update_position(connection, position_id=position_id, position=position)
        return _to_position_out(row)

    @app.delete("/api/portfolios/{portfolio_id}/positions/{position_id}", status_code=204)
    def delete_manual_position(
        portfolio_id: UUID,
        position_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> None:
        _require_manual_position(connection, portfolio_id, position_id)
        repository.delete_position(connection, position_id)

    @app.get("/api/portfolios/{portfolio_id}/metrics", response_model=MetricsOut)
    async def get_metrics(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> MetricsOut:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        rows = _current_position_rows(connection, portfolio_id)
        fx_client = fx_client_factory()
        positions_with_base_value = []
        for row in rows:
            position = _position_row_to_domain(row)
            live_value = await _live_market_value(position, price_ratio_fetcher)
            if live_value is not None:
                position = position.model_copy(update={"market_value": live_value})
            positions_with_base_value.append(
                (position, await _base_currency_value(position, fx_client))
            )

        try:
            weights = compute_weights(positions_with_base_value)
        except ValueError:
            # Empty portfolio, or every position values at 0 -- nothing to
            # divide by, not a server error.
            return MetricsOut(
                position_count=len(rows),
                total_value=None,
                base_currency=BASE_CURRENCY,
                hhi=None,
                effective_positions=None,
                top5_share=None,
                allocation_by_asset_class={},
                allocation_by_currency={},
            )

        total_value = sum((w.base_currency_value for w in weights.weighted_positions), Decimal(0))
        return MetricsOut(
            position_count=len(rows),
            total_value=total_value,
            base_currency=BASE_CURRENCY,
            hhi=weights.hhi.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP),
            effective_positions=weights.effective_positions.quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            ),
            top5_share=_as_percent(weights.top5_share),
            allocation_by_asset_class={
                key: _as_percent(value)
                for key, value in weights.allocation_by_asset_class.items()
            },
            allocation_by_currency={
                key: _as_percent(value) for key, value in weights.allocation_by_currency.items()
            },
        )

    @app.get("/api/portfolios/{portfolio_id}/aggregators", response_model=list[AggregatorOut])
    async def list_portfolio_aggregators(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> list[AggregatorOut]:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        all_aggregators = repository.list_aggregators(connection, portfolio_id)
        all_by_id = {a.id: a for a in all_aggregators}
        values_by_key = await _instrument_values_by_key(
            connection, portfolio_id, fx_client_factory()
        )
        return [_to_aggregator_out(a, all_by_id, values_by_key) for a in all_aggregators]

    @app.post(
        "/api/portfolios/{portfolio_id}/aggregators",
        response_model=AggregatorOut,
        status_code=201,
    )
    async def create_portfolio_aggregator(
        portfolio_id: UUID,
        payload: AggregatorCreate,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> AggregatorOut:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        _require_existing_aggregators(connection, portfolio_id, payload.member_aggregator_ids)

        created = repository.create_aggregator(
            connection,
            portfolio_id=portfolio_id,
            name=payload.name,
            member_instrument_keys=payload.member_instrument_keys,
            member_aggregator_ids=payload.member_aggregator_ids,
        )
        all_aggregators = repository.list_aggregators(connection, portfolio_id)
        all_by_id = {a.id: a for a in all_aggregators}
        values_by_key = await _instrument_values_by_key(
            connection, portfolio_id, fx_client_factory()
        )
        return _to_aggregator_out(created, all_by_id, values_by_key)

    @app.put(
        "/api/portfolios/{portfolio_id}/aggregators/{aggregator_id}",
        response_model=AggregatorOut,
    )
    async def update_portfolio_aggregator(
        portfolio_id: UUID,
        aggregator_id: UUID,
        payload: AggregatorCreate,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> AggregatorOut:
        _require_own_aggregator(connection, portfolio_id, aggregator_id)
        _require_existing_aggregators(connection, portfolio_id, payload.member_aggregator_ids)

        all_aggregators = repository.list_aggregators(connection, portfolio_id)
        all_by_id = {a.id: a for a in all_aggregators}
        try:
            validate_no_cycle(aggregator_id, payload.member_aggregator_ids, all_by_id)
        except CycleError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        updated = repository.update_aggregator(
            connection,
            aggregator_id=aggregator_id,
            name=payload.name,
            member_instrument_keys=payload.member_instrument_keys,
            member_aggregator_ids=payload.member_aggregator_ids,
        )
        all_by_id[aggregator_id] = updated
        values_by_key = await _instrument_values_by_key(
            connection, portfolio_id, fx_client_factory()
        )
        return _to_aggregator_out(updated, all_by_id, values_by_key)

    @app.delete(
        "/api/portfolios/{portfolio_id}/aggregators/{aggregator_id}",
        status_code=204,
    )
    def delete_portfolio_aggregator(
        portfolio_id: UUID,
        aggregator_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> None:
        _require_own_aggregator(connection, portfolio_id, aggregator_id)
        repository.delete_aggregator(connection, aggregator_id)

    @app.get(
        "/api/portfolios/{portfolio_id}/report",
        response_model=ReportOut | None,
    )
    def get_cached_report(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> ReportOut | None:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        context = _current_reporting_context(connection, portfolio_id)
        if context is None:
            return None
        snapshot_id, _valuation_date = context
        cached = repository.find_latest_report(connection, snapshot_id)
        return _to_report_out(cached) if cached is not None else None

    @app.post("/api/portfolios/{portfolio_id}/report", response_model=ReportOut)
    async def generate_portfolio_report(
        portfolio_id: UUID,
        regenerate: bool = False,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> ReportOut:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        context = _current_reporting_context(connection, portfolio_id)
        if context is None:
            raise HTTPException(status_code=422, detail="Portfolio has no positions yet")
        snapshot_id, valuation_date = context

        lock = app.state.report_locks.setdefault(portfolio_id, asyncio.Lock())
        async with lock:
            if not regenerate:
                cached = repository.find_latest_report(connection, snapshot_id)
                if cached is not None:
                    return _to_report_out(cached)

            rows = _current_position_rows(connection, portfolio_id)
            positions = [_position_row_to_domain(row) for row in rows]
            fx_client = fx_client_factory()
            positions_with_base_value = [
                (position, await _base_currency_value(position, fx_client))
                for position in positions
            ]
            try:
                weights = compute_weights(positions_with_base_value)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

            llm_client = llm_client_factory()
            prompt_registry = app.state.prompt_registry
            cost_before = llm_client.total_cost_usd

            instrument_metadata: dict[str, InstrumentMetadata] = {}
            category_weight: dict[str, Decimal] = {}
            try:
                for index, weighted in enumerate(weights.weighted_positions):
                    key = str(index)
                    category = await classify_sector(
                        weighted.position, llm_client, prompt_registry, MODEL
                    )
                    category_weight[category] = (
                        category_weight.get(category, Decimal(0)) + weighted.weight
                    )
                    instrument_metadata[key] = InstrumentMetadata(
                        name=weighted.position.instrument_name,
                        category=category,
                        exchange_code=weighted.position.exchange_code,
                        currency=weighted.position.market_currency,
                    )
            except genai_errors.APIError as exc:
                raise _llm_unavailable(exc) from exc

            metrics = MetricsJson(
                valuation_date=valuation_date,
                base_currency=BASE_CURRENCY,
                weights=weights,
                risk=None,  # metrics/risk.py needs yfinance history -- out of scope (S5/S6)
                allocation_by_category=category_weight,
            )

            try:
                content_md = await build_report(
                    metrics, instrument_metadata, llm_client, prompt_registry, MODEL
                )
            except ReportRejectedError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except genai_errors.APIError as exc:
                raise _llm_unavailable(exc) from exc

            cost_usd = llm_client.total_cost_usd - cost_before
            row = repository.create_report(
                connection,
                snapshot_id=snapshot_id,
                model=MODEL,
                cost_usd=cost_usd,
                content_md=content_md,
            )
            return _to_report_out(row)

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


def _require_manual_position(
    connection: duckdb.DuckDBPyConnection, portfolio_id: UUID, position_id: UUID
) -> PortfolioRow:
    # 404s a position from a file import too (REQ-011 forbids editing it,
    # and the frontend never offers the action for one) -- not a path real
    # use reaches, just a defensive backstop.
    portfolio = repository.get_portfolio(connection, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    manual_snapshot = repository.find_manual_snapshot(connection, portfolio_id)
    position = repository.get_position(connection, position_id)
    if position is None or manual_snapshot is None or position[1] != manual_snapshot[0]:
        raise HTTPException(status_code=404, detail="Position not found")

    return portfolio


def _current_position_rows(
    connection: duckdb.DuckDBPyConnection, portfolio_id: UUID
) -> list[PositionRow]:
    # Same "current state" as PortfolioDetail.tsx's own merge (S4): the
    # latest real import, if any, plus every manually added position.
    rows: list[PositionRow] = []
    snapshots = repository.list_snapshots(connection, portfolio_id)
    if snapshots:
        rows.extend(repository.list_positions(connection, snapshots[0][0]))
    manual_snapshot = repository.find_manual_snapshot(connection, portfolio_id)
    if manual_snapshot is not None:
        rows.extend(repository.list_positions(connection, manual_snapshot[0]))
    return rows


def _current_reporting_context(
    connection: duckdb.DuckDBPyConnection, portfolio_id: UUID
) -> tuple[UUID, date_type] | None:
    # The snapshot id a report gets cached against, and the valuation date
    # put in front of the LLM -- the latest real import if one exists
    # (its own valuation_date), else the manual-positions container (dated
    # today, since manual positions don't carry one collective date).
    # Editing a manual position afterwards doesn't change this id, so a
    # cached report can go stale until the owner clicks "Odśwież" --
    # accepted trade-off (REQ-041 already provides that escape hatch).
    snapshots = repository.list_snapshots(connection, portfolio_id)
    if snapshots:
        return snapshots[0][0], snapshots[0][3]
    manual_snapshot = repository.find_manual_snapshot(connection, portfolio_id)
    if manual_snapshot is not None:
        return manual_snapshot[0], date_type.today()
    return None


async def _build_manual_position(
    payload: PositionCreate,
    *,
    account_type: str,
    market_value: Decimal,
    openfigi_client: OpenFigiClient | None,
    quote_currency_fetcher: Callable[[str], str | None],
) -> Position:
    position = Position(
        broker=repository.MANUAL_BROKER,
        account_type=account_type,
        instrument_name=payload.instrument_name,
        isin=payload.isin,
        symbol=payload.symbol,
        asset_class=payload.asset_class,
        quantity=payload.quantity,
        avg_cost=payload.avg_cost,
        cost_currency="PLN",
        market_value=market_value,
        market_currency="PLN",
        valuation_date=date_type.today(),
    )
    return await _resolve_manual_identification(position, openfigi_client, quote_currency_fetcher)


async def _resolve_manual_identification(
    position: Position,
    openfigi_client: OpenFigiClient | None,
    quote_currency_fetcher: Callable[[str], str | None],
) -> Position:
    # Mirrors service.py's own (module-private) _resolve_identifications for
    # a single position -- same reasoning as _flag_injection_warnings: that
    # function is P1-private, portfolio_webapp may only reach its public
    # surface (docs/ARCHITECTURE.md rule 6).
    if openfigi_client is None or position.isin is None:
        return position
    identification = await openfigi_client.resolve_by_isin(position.isin, "PLN", None)
    quote_currency = None
    if identification.ticker is not None:
        yfinance_ticker = to_yahoo_ticker(identification.ticker, identification.exchange_code)
        try:
            quote_currency = await asyncio.to_thread(quote_currency_fetcher, yfinance_ticker)
        except Exception:
            # yfinance is unofficial and sometimes blocked (docs/DATA-SOURCES.md)
            # -- a failed lookup must not break saving the position.
            quote_currency = None
    return position.model_copy(
        update={
            "resolution_status": identification.status,
            "figi": identification.figi,
            "ticker": identification.ticker,
            "exchange_code": identification.exchange_code,
            "identification_rule": identification.identification_rule,
            "quote_currency": quote_currency,
        }
    )


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
    snapshot_row = repository.create_snapshot(
        connection, portfolio_id=portfolio_id, broker=broker, valuation_date=valuation_date
    )
    repository.insert_positions(connection, snapshot_id=snapshot_row[0], positions=result.positions)
    position_rows = repository.list_positions(connection, snapshot_row[0])

    return ImportResponse(
        # Freshly imported -- already "now", no live-refresh attempt needed.
        snapshot=_to_snapshot_out(snapshot_row, [_to_position_out(p) for p in position_rows]),
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
    # cursor(), not the shared connection directly: FastAPI runs sync
    # endpoints in a threadpool, and concurrent execute() calls on one
    # DuckDB connection from different threads corrupt each other's result
    # rows (reproduced). cursor() shares the same database but is
    # independent per call.
    return request.app.state.db.cursor()


def _to_portfolio_out(row: PortfolioRow) -> PortfolioOut:
    id_, name, broker, account_type, created_at = row
    return PortfolioOut(
        id=id_, name=name, broker=broker, account_type=account_type, created_at=created_at
    )


def _to_position_out(row: PositionRow, *, live_market_value: Decimal | None = None) -> PositionOut:
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
        quote_currency,
    ) = row
    effective_market_value = market_value if live_market_value is None else live_market_value
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
        market_value=effective_market_value,
        market_currency=market_currency,
        valuation_date=valuation_date,
        resolution_status=resolution_status,
        figi=figi,
        ticker=ticker,
        exchange_code=exchange_code,
        identification_rule=identification_rule,
        quote_currency=quote_currency,
        return_pct=_return_pct(
            quantity=quantity,
            avg_cost=avg_cost,
            cost_currency=cost_currency,
            market_value=effective_market_value,
            market_currency=market_currency,
        ),
    )


async def _to_position_out_with_live_value(
    row: PositionRow, price_ratio_fetcher: Callable[[str, date_type], Decimal | None]
) -> PositionOut:
    live_value = await _live_market_value(_position_row_to_domain(row), price_ratio_fetcher)
    return _to_position_out(row, live_market_value=live_value)


async def _live_market_value(
    position: Position, price_ratio_fetcher: Callable[[str, date_type], Decimal | None]
) -> Decimal | None:
    # Ratio of latest close to the close on the position's own valuation
    # date, applied to the already-stored (already-correct-currency) value
    # -- never needs to know what currency the ticker is quoted in (#188).
    # Manual positions are the owner's own explicit input, left untouched.
    if position.broker == repository.MANUAL_BROKER:
        return None
    if position.market_value is None or position.quantity <= 0:
        return None
    yfinance_ticker = (
        to_yahoo_ticker(position.ticker, position.exchange_code)
        if position.ticker is not None
        else position.symbol
    )
    if yfinance_ticker is None:
        return None

    try:
        ratio = await asyncio.to_thread(
            price_ratio_fetcher, yfinance_ticker, position.valuation_date
        )
    except Exception:
        # yfinance is unofficial and sometimes blocked (docs/DATA-SOURCES.md)
        # -- a live-refresh failure must fall back to the stored value, never
        # break the page.
        return None
    if ratio is None:
        return None
    return (position.market_value * ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _return_pct(
    *,
    quantity: Decimal,
    avg_cost: Decimal | None,
    cost_currency: str | None,
    market_value: Decimal | None,
    market_currency: str | None,
) -> Decimal | None:
    # Short/derivative positions (quantity <= 0) need a sign-aware formula --
    # the naive one below would report a loss as a gain -- out of scope here.
    if avg_cost is None or market_value is None or quantity <= 0:
        return None
    if cost_currency != market_currency:
        return None

    cost_basis = quantity * avg_cost
    if cost_basis == 0:
        return None

    return ((market_value - cost_basis) / cost_basis * 100).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )


def _position_row_to_domain(row: PositionRow) -> Position:
    (
        _id,
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
        quote_currency,
    ) = row
    return Position(
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
        quote_currency=quote_currency,
    )


async def _base_currency_value(position: Position, fx_client: NbpFxClient) -> Decimal:
    # Mirrors report/orchestrator.py's own (module-private) _base_currency_value
    # -- same reasoning as _flag_injection_warnings: P1-private, portfolio_webapp
    # may only reach its public surface (docs/ARCHITECTURE.md rule 6).
    if position.market_value is None or position.market_currency is None:
        return Decimal(0)
    return await convert_to_base_currency(
        position.market_value, position.market_currency, position.valuation_date, fx_client
    )


async def _instrument_values_by_key(
    connection: duckdb.DuckDBPyConnection, portfolio_id: UUID, fx_client: NbpFxClient
) -> dict[str, Decimal]:
    # Live, non-live-price-refreshed value on purpose -- aggregators sum
    # whatever the portfolio's positions already show (same stored value
    # metrics.py would use before #190's live-refresh, kept simple here:
    # an aggregate is a grouping/display concern, not itself a live quote).
    values: dict[str, Decimal] = {}
    for row in _current_position_rows(connection, portfolio_id):
        position = _position_row_to_domain(row)
        key = instrument_key(position)
        values[key] = values.get(key, Decimal(0)) + await _base_currency_value(position, fx_client)
    return values


def _to_aggregator_out(
    aggregator: Aggregator,
    all_by_id: dict[UUID, Aggregator],
    values_by_key: dict[str, Decimal],
) -> AggregatorOut:
    value = resolve_value(aggregator, all_by_id, values_by_key)
    return AggregatorOut(
        id=aggregator.id,
        portfolio_id=aggregator.portfolio_id,
        name=aggregator.name,
        member_instrument_keys=aggregator.member_instrument_keys,
        member_aggregator_ids=aggregator.member_aggregator_ids,
        value=value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        base_currency=BASE_CURRENCY,
    )


def _require_existing_aggregators(
    connection: duckdb.DuckDBPyConnection, portfolio_id: UUID, member_aggregator_ids: list[UUID]
) -> None:
    existing_ids = {a.id for a in repository.list_aggregators(connection, portfolio_id)}
    unknown = [str(mid) for mid in member_aggregator_ids if mid not in existing_ids]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown aggregator id(s) in this portfolio: {', '.join(unknown)}",
        )


def _require_own_aggregator(
    connection: duckdb.DuckDBPyConnection, portfolio_id: UUID, aggregator_id: UUID
) -> Aggregator:
    aggregator = repository.get_aggregator(connection, aggregator_id)
    if aggregator is None or aggregator.portfolio_id != portfolio_id:
        raise HTTPException(status_code=404, detail="Aggregator not found")
    return aggregator


def _as_percent(fraction: Decimal) -> Decimal:
    return (fraction * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _llm_unavailable(exc: genai_errors.APIError) -> HTTPException:
    # Covers both ServerError (5xx, e.g. "model overloaded") and ClientError
    # (4xx, e.g. Gemini's own rate limit) -- either way the report can't be
    # generated right now, and the raw exception must not reach the owner as
    # an opaque 500 (issue #204).
    return HTTPException(
        status_code=503,
        detail=f"Model AI chwilowo niedostępny ({exc.message}) -- spróbuj ponownie za chwilę.",
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


def _to_report_out(row: repository.ReportRow) -> ReportOut:
    id_, snapshot_id, generated_at, model, cost_usd, content_md = row
    return ReportOut(
        id=id_,
        snapshot_id=snapshot_id,
        generated_at=generated_at,
        model=model,
        cost_usd=cost_usd,
        content_md=content_md,
    )


def _to_snapshot_out(row: SnapshotRow, positions: list[PositionOut]) -> SnapshotOut:
    id_, portfolio_id, broker, valuation_date, imported_at, date_min, date_max = row
    return SnapshotOut(
        id=id_,
        portfolio_id=portfolio_id,
        broker=broker,
        valuation_date=valuation_date,
        imported_at=imported_at,
        source_file_date_min=date_min,
        source_file_date_max=date_max,
        positions=positions,
    )
