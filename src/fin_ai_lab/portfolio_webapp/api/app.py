import asyncio
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date as date_type
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import cast
from uuid import UUID

import duckdb
from fastapi import Depends, FastAPI, HTTPException
from google.genai import errors as genai_errors

from fin_ai_lab.core.llm.client import CostTrackingLlmClient, LlmClient
from fin_ai_lab.core.llm.embeddings import EmbeddingClient
from fin_ai_lab.core.llm.trace import TRACES_DIR
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag.service import INDEX_PATH as FILINGS_INDEX_PATH
from fin_ai_lab.filings_rag.service import PROMPTS_DIR as FILINGS_RAG_PROMPTS_DIR
from fin_ai_lab.filings_rag.service import SavedIndexCache
from fin_ai_lab.investment_committee.service import (
    BudgetGuard,
    CommitteeReport,
    ComparisonReport,
    compare_committee_vs_single,
    run_committee,
    run_single_agent,
)
from fin_ai_lab.market_pulse.service import STATE_PATH as MARKET_PULSE_STATE_PATH
from fin_ai_lab.market_pulse.service import FredClient, NbpClient
from fin_ai_lab.news_classifier.service import CORPUS_PATH as NEWS_CLASSIFIER_CORPUS_PATH
from fin_ai_lab.portfolio_webapp import db, repository
from fin_ai_lab.portfolio_webapp.aggregators import (
    Aggregator,
    CycleError,
    instrument_key,
    resolve_value,
    validate_no_cycle,
)
from fin_ai_lab.portfolio_webapp.api import (
    benchmark,
    breakdowns,
    dividends,
    filings_rag,
    imports,
    market_pulse,
    metrics,
    news_classifier,
    portfolios,
    positions,
    shares,
    system,
    valuation,
)
from fin_ai_lab.portfolio_webapp.api.common import (
    base_currency_value,
    current_position_rows,
    get_db,
    llm_unavailable,
    position_row_to_domain,
)
from fin_ai_lab.portfolio_webapp.api.defaults import (
    BASE_CURRENCY,
    COMMITTEE_BUDGET_USD,
    COMMITTEE_MAX_ITERATIONS,
    COMPARISON_REPORT_PATH,
    CONFIRMATION_TIMEOUT_S,
    INVESTMENT_COMMITTEE_PROMPTS_DIR,
    MARKET_PULSE_BRIEFS_DIR,
    MARKET_PULSE_PROMPTS_DIR,
    MODEL,
    PORTFOLIO_PROMPTS_DIR,
    REPORT_PROMPTS_DIR,
    SECTOR_PROMPTS_DIR,
    _default_embedding_client,
    _default_fred_client,
    _default_llm_client,
    _fetch_adjusted_daily_closes,
    _fetch_daily_closes,
)
from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.benchmark import normalize_ticker
from fin_ai_lab.portfolio_webapp.dividend_forecast_builder import DividendsFetcher
from fin_ai_lab.portfolio_webapp.instrument_overrides_builder import (
    UnknownYahooSymbolError,
    YahooUnavailableError,
    checked_override,
)
from fin_ai_lab.portfolio_webapp.instruments_builder import build_instruments, load_link_state
from fin_ai_lab.portfolio_webapp.schemas import (
    AggregatorCreate,
    AggregatorOut,
    CommitteeAnalysisRequest,
    CommitteeJobOut,
    CommitteeJobStatus,
    CommitteeVariant,
    ConfirmBudgetRequest,
    InstrumentDetachIn,
    InstrumentLinkIn,
    InstrumentOwnerDataIn,
    InstrumentsOut,
    ReportOut,
)
from fin_ai_lab.portfolio_webapp.valuation_builder import (
    DailyClosesFetcher,
    build_valuation,
)
from fin_ai_lab.portfolio_xray.canonical import Portfolio
from fin_ai_lab.portfolio_xray.identification.openfigi import OpenFigiClient
from fin_ai_lab.portfolio_xray.metrics.fx import NbpFxClient
from fin_ai_lab.portfolio_xray.metrics.price_history import (
    fetch_dividends,
    fetch_quote_currency,
    price_change_ratio,
)
from fin_ai_lab.portfolio_xray.metrics.weights import compute_weights
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry
from fin_ai_lab.portfolio_xray.report.builder import ReportRejectedError, build_report
from fin_ai_lab.portfolio_xray.report.models import InstrumentMetadata, MetricsJson
from fin_ai_lab.portfolio_xray.sectors.classifier import classify_sector


def create_app(
    db_path: Path = db.DEFAULT_DB_PATH,
    # Injected rather than constructed inline (SOLID/D): production gets a
    # real, network-calling client by default; tests substitute `lambda: None`
    # so importing a synthetic file never depends on the network, the same
    # guarantee P1's own tests already rely on for `openfigi_client=None`.
    openfigi_client_factory: Callable[[], OpenFigiClient | None] = OpenFigiClient,
    # Same reasoning as openfigi_client_factory: tests substitute a
    # FakeLlmClient with canned responses instead of calling Gemini.
    llm_client_factory: Callable[[], CostTrackingLlmClient] = _default_llm_client,
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
    # Same reasoning as the factories above -- production reads the real,
    # shared trace directory every LlmClient writes to; tests point this at
    # tmp_path with synthetic trace files instead.
    traces_dir: Path = TRACES_DIR,
    # Read-only files this app never writes -- tests point these at tmp_path
    # instead of the real data/ directory, same reasoning as traces_dir.
    briefs_dir: Path = MARKET_PULSE_BRIEFS_DIR,
    market_pulse_state_path: Path = MARKET_PULSE_STATE_PATH,
    # Same DI reasoning as openfigi_client_factory -- FredClient needs a real
    # API key and hits the network; tests substitute a key-less stub since
    # /market-pulse/ask never actually triggers a tool call against a
    # FakeLlmClient.
    fred_client_factory: Callable[[], FredClient] = _default_fred_client,
    nbp_client_factory: Callable[[], NbpClient] = NbpClient,
    comparison_report_path: Path = COMPARISON_REPORT_PATH,
    # #225: the index saved by `filings-rag build-index` -- read-only here,
    # this app never builds or extends it. Same DI reasoning as briefs_dir.
    filings_index_path: Path = FILINGS_INDEX_PATH,
    # Same DI reasoning as llm_client_factory -- tests substitute a
    # FakeEmbeddingClient. None means no API key: questions can't be asked.
    embedding_client_factory: Callable[[], EmbeddingClient | None] = _default_embedding_client,
    news_classifier_corpus_path: Path = NEWS_CLASSIFIER_CORPUS_PATH,
    # Same DI reasoning as every constant above -- tests force an immediate
    # budget exhaustion (e.g. max_iterations=0) to exercise the confirm-flow
    # deterministically, without fabricating real LLM cost.
    committee_budget_usd: Decimal = COMMITTEE_BUDGET_USD,
    committee_max_iterations: int = COMMITTEE_MAX_ITERATIONS,
    # S10 value history -- same DI reasoning as price_ratio_fetcher: tests
    # substitute canned daily closes instead of calling yfinance, and pin
    # "today" so a day-by-day series has a known length.
    daily_closes_fetcher: DailyClosesFetcher = _fetch_daily_closes,
    today_provider: Callable[[], date_type] = date_type.today,
    # #266 dividend estimate -- same DI reasoning as daily_closes_fetcher:
    # tests substitute canned per-share dividends instead of calling yfinance.
    dividends_fetcher: DividendsFetcher = fetch_dividends,
    # #273 benchmark comparison -- same DI reasoning again; dividend-adjusted
    # closes, so a benchmark's return includes its dividends.
    benchmark_closes_fetcher: DailyClosesFetcher = _fetch_adjusted_daily_closes,
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
        prompt_registry.load_dir(MARKET_PULSE_PROMPTS_DIR)
        prompt_registry.load_dir(INVESTMENT_COMMITTEE_PROMPTS_DIR)
        prompt_registry.load_dir(FILINGS_RAG_PROMPTS_DIR)
        app.state.prompt_registry = prompt_registry
        app.state.filings_index_cache = SavedIndexCache(filings_index_path)
        # One lock per portfolio (02-spec.md edge case): a second "generuj"
        # while the first is still running waits for it instead of starting
        # a parallel LLM call for the same report.
        app.state.report_locks = {}  # dict[UUID, asyncio.Lock]
        # #226: bridges a committee job's blocking BudgetGuard.on_budget_exceeded
        # callback (running in a worker thread, see _make_confirm_callback) to
        # the POST .../confirm endpoint (running on the main event loop).
        app.state.committee_confirmations = {}  # dict[UUID, threading.Event]
        app.state.committee_confirmation_decisions = {}  # dict[UUID, bool]
        # Keeps a strong reference to every in-flight job task -- asyncio
        # only guarantees a fire-and-forget task survives if something else
        # holds onto it, otherwise it can be garbage-collected mid-run.
        app.state.committee_job_tasks = set()  # set[asyncio.Task]
        yield
        app.state.db.close()

    app = FastAPI(title="Portfel", lifespan=lifespan)

    deps = AppDeps(
        openfigi_client_factory=openfigi_client_factory,
        llm_client_factory=llm_client_factory,
        parser_registry_factory=parser_registry_factory,
        fx_client_factory=fx_client_factory,
        price_ratio_fetcher=price_ratio_fetcher,
        quote_currency_fetcher=quote_currency_fetcher,
        traces_dir=traces_dir,
        briefs_dir=briefs_dir,
        market_pulse_state_path=market_pulse_state_path,
        fred_client_factory=fred_client_factory,
        nbp_client_factory=nbp_client_factory,
        comparison_report_path=comparison_report_path,
        embedding_client_factory=embedding_client_factory,
        news_classifier_corpus_path=news_classifier_corpus_path,
        committee_budget_usd=committee_budget_usd,
        committee_max_iterations=committee_max_iterations,
        daily_closes_fetcher=daily_closes_fetcher,
        today_provider=today_provider,
        dividends_fetcher=dividends_fetcher,
        benchmark_closes_fetcher=benchmark_closes_fetcher,
    )
    for build in (
        system,
        market_pulse,
        news_classifier,
        filings_rag,
        portfolios,
        imports,
        positions,
        metrics,
        valuation,
        benchmark,
        dividends,
        breakdowns,
        shares,
    ):
        app.include_router(build.build_router(deps))

    async def instruments_out(connection: duckdb.DuckDBPyConnection) -> InstrumentsOut:
        # Every portfolio, whatever screen asks: identity is global (S12).
        state = load_link_state(connection)
        valuation = await build_valuation(
            connection,
            repository.list_portfolios(connection),
            today=today_provider(),
            refresh=False,
            closes_fetcher=daily_closes_fetcher,
            fx_client=fx_client_factory(),
            link_state=state,
        )
        return build_instruments(state, valuation, repository.list_instrument_overrides(connection))

    @app.get("/api/instruments", response_model=InstrumentsOut)
    async def get_instruments(
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> InstrumentsOut:
        return await instruments_out(connection)

    @app.post("/api/instruments/links", response_model=InstrumentsOut)
    async def decide_instrument_link(
        payload: InstrumentLinkIn,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> InstrumentsOut:
        # REQ-091: the owner's answer for one pair -- "the same" joins them
        # into one asset, "different" keeps them apart for good (even with a
        # shared FIGI) and stops suggesting the pair.
        if payload.key_a == payload.key_b:
            raise HTTPException(status_code=422, detail="Wybierz dwa różne instrumenty.")
        known = {i.key for i in load_link_state(connection).instruments}
        for key in (payload.key_a, payload.key_b):
            if key not in known:
                raise HTTPException(status_code=422, detail=f"Nieznany instrument: {key}")
        repository.set_instrument_decision(
            connection, key_a=payload.key_a, key_b=payload.key_b, same=payload.same
        )
        return await instruments_out(connection)

    @app.post("/api/instruments/detach", response_model=InstrumentsOut)
    async def detach_instrument(
        payload: InstrumentDetachIn,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> InstrumentsOut:
        # REQ-094: takes one instrument out of its asset; the rest of the
        # asset stays joined, even where only this one linked them.
        state = load_link_state(connection)
        if payload.key not in {i.key for i in state.instruments}:
            raise HTTPException(status_code=422, detail=f"Nieznany instrument: {payload.key}")
        asset_key = state.identities.asset_key(payload.key)
        others = [k for k in state.identities.members(asset_key) if k != payload.key]
        repository.delete_same_decisions(connection, payload.key)
        for other in others:
            repository.set_instrument_decision(
                connection, key_a=payload.key, key_b=other, same=False
            )
        after = load_link_state(connection).identities
        if len({after.asset_key(k) for k in others}) > 1:
            for other in others[1:]:
                repository.set_instrument_decision(
                    connection, key_a=others[0], key_b=other, same=True
                )
        return await instruments_out(connection)

    @app.post("/api/instruments/owner-data", response_model=InstrumentsOut)
    async def save_instrument_owner_data(
        payload: InstrumentOwnerDataIn,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> InstrumentsOut:
        # #285: the owner's own Yahoo symbol and quote currency for one held
        # instrument; both empty clears the entry. A manual position is the
        # owner's own figure and is never priced from quotes.
        instrument = next(
            (i for i in load_link_state(connection).instruments if i.key == payload.key), None
        )
        if instrument is None:
            raise HTTPException(status_code=422, detail=f"Nieznany instrument: {payload.key}")
        if instrument.is_manual:
            raise HTTPException(
                status_code=422,
                detail="Pozycja ręczna ma własną wartość -- nie wycenia się jej z notowań.",
            )
        ticker = None
        if payload.yahoo_ticker is not None and payload.yahoo_ticker.strip():
            ticker = normalize_ticker(payload.yahoo_ticker)
            if ticker is None:
                raise HTTPException(
                    status_code=422,
                    detail="Nieprawidłowy symbol -- dozwolone litery, cyfry i znaki . ^ = -",
                )
        if ticker is None and payload.quote_currency is None:
            repository.delete_instrument_override(connection, payload.key)
            return await instruments_out(connection)
        try:
            override = await checked_override(
                payload.key,
                ticker,
                payload.quote_currency,
                today=today_provider(),
                closes_fetcher=daily_closes_fetcher,
                quote_currency_fetcher=quote_currency_fetcher,
            )
        except UnknownYahooSymbolError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Yahoo nie zna symbolu {exc.ticker} -- sprawdź go na finance.yahoo.com.",
            ) from None
        except YahooUnavailableError:
            raise HTTPException(
                status_code=502, detail="Yahoo nie odpowiedziało -- spróbuj ponownie za chwilę."
            ) from None
        repository.save_instrument_override(connection, override)
        return await instruments_out(connection)

    @app.get("/api/portfolios/{portfolio_id}/aggregators", response_model=list[AggregatorOut])
    async def list_portfolio_aggregators(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
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
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
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
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
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
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> None:
        _require_own_aggregator(connection, portfolio_id, aggregator_id)
        repository.delete_aggregator(connection, aggregator_id)

    @app.get(
        "/api/portfolios/{portfolio_id}/report",
        response_model=ReportOut | None,
    )
    def get_cached_report(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
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
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
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

            rows = current_position_rows(connection, portfolio_id)
            positions = [position_row_to_domain(row) for row in rows]
            fx_client = fx_client_factory()
            positions_with_base_value = [
                (position, await base_currency_value(position, fx_client)) for position in positions
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
                raise llm_unavailable(exc) from exc

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
                raise llm_unavailable(exc) from exc

            cost_usd = llm_client.total_cost_usd - cost_before
            row = repository.create_report(
                connection,
                snapshot_id=snapshot_id,
                model=MODEL,
                cost_usd=cost_usd,
                content_md=content_md,
            )
            return _to_report_out(row)

    @app.post(
        "/api/portfolios/{portfolio_id}/committee-analysis",
        response_model=CommitteeJobOut,
    )
    async def start_committee_analysis(
        portfolio_id: UUID,
        payload: CommitteeAnalysisRequest,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> CommitteeJobOut:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        context = _current_reporting_context(connection, portfolio_id)
        if context is None:
            raise HTTPException(status_code=422, detail="Portfolio has no positions yet")
        snapshot_id, valuation_date = context

        if not payload.regenerate:
            cached = repository.find_latest_done_committee_job(
                connection, snapshot_id, payload.variant
            )
            if cached is not None:
                return _to_committee_job_out(cached)

        rows = current_position_rows(connection, portfolio_id)
        positions = [position_row_to_domain(row) for row in rows]
        portfolio = Portfolio(positions=positions, valuation_date=valuation_date)

        job_row = repository.create_committee_job(
            connection,
            portfolio_id=portfolio_id,
            snapshot_id=snapshot_id,
            variant=payload.variant,
            model=MODEL,
        )
        job_id = job_row[0]

        task = asyncio.create_task(
            _run_committee_job(job_id, portfolio, str(portfolio_id), payload.variant)
        )
        app.state.committee_job_tasks.add(task)
        task.add_done_callback(app.state.committee_job_tasks.discard)

        return _to_committee_job_out(job_row)

    @app.get(
        "/api/portfolios/{portfolio_id}/committee-analysis/{job_id}",
        response_model=CommitteeJobOut,
    )
    def get_committee_analysis_job(
        portfolio_id: UUID,
        job_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> CommitteeJobOut:
        job_row = repository.get_committee_job(connection, job_id)
        if job_row is None or job_row[1] != portfolio_id:
            raise HTTPException(status_code=404, detail="Job not found")
        return _to_committee_job_out(job_row)

    @app.post(
        "/api/portfolios/{portfolio_id}/committee-analysis/{job_id}/confirm",
        response_model=CommitteeJobOut,
    )
    def confirm_committee_budget(
        portfolio_id: UUID,
        job_id: UUID,
        payload: ConfirmBudgetRequest,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> CommitteeJobOut:
        job_row = repository.get_committee_job(connection, job_id)
        if job_row is None or job_row[1] != portfolio_id:
            raise HTTPException(status_code=404, detail="Job not found")

        event = app.state.committee_confirmations.get(job_id)
        if job_row[4] != "awaiting_confirmation" or event is None:
            raise HTTPException(status_code=409, detail="Job is not awaiting confirmation")

        app.state.committee_confirmation_decisions[job_id] = payload.approve
        event.set()

        return _to_committee_job_out(job_row)

    def _make_confirm_callback(job_id: UUID) -> Callable[[], bool]:
        # Runs INSIDE the worker thread started by asyncio.to_thread below
        # (BudgetGuard.on_budget_exceeded is called synchronously, deep in
        # run_committee/run_single_agent's call graph) -- blocking here
        # blocks only that thread, never the main event loop, so the server
        # stays responsive to GET/confirm requests while a job waits.
        def on_budget_exceeded() -> bool:
            repository.update_committee_job_status(
                app.state.db.cursor(), job_id, "awaiting_confirmation"
            )
            event = threading.Event()
            app.state.committee_confirmations[job_id] = event
            answered = event.wait(timeout=CONFIRMATION_TIMEOUT_S)
            decision = app.state.committee_confirmation_decisions.pop(job_id, False)
            if not answered:
                decision = False
            app.state.committee_confirmations.pop(job_id, None)
            repository.update_committee_job_status(app.state.db.cursor(), job_id, "running")
            return decision

        return on_budget_exceeded

    def _run_variant_sync(
        variant: str,
        portfolio: Portfolio,
        portfolio_id: str,
        fred_client: FredClient,
        nbp_client: NbpClient,
        llm_client: LlmClient,
        prompt_registry: PromptRegistry,
        fx_client: NbpFxClient,
        budget: BudgetGuard | None,
    ) -> CommitteeReport | ComparisonReport:
        # A fresh event loop for this worker thread (asyncio.to_thread hands
        # us a plain OS thread with none running) -- safe and standard for
        # bridging blocking code into an async server.
        if variant == "single":
            assert budget is not None
            return asyncio.run(
                run_single_agent(
                    portfolio,
                    portfolio_id,
                    fred_client,
                    nbp_client,
                    llm_client,
                    prompt_registry,
                    MODEL,
                    budget,
                )
            )
        if variant == "committee":
            assert budget is not None
            return asyncio.run(
                run_committee(
                    portfolio,
                    portfolio_id,
                    fred_client,
                    nbp_client,
                    llm_client,
                    prompt_registry,
                    MODEL,
                    budget,
                    fx_client=fx_client,
                )
            )
        # "compare": qa_target.compare_committee_vs_single builds its own,
        # non-overridable BudgetGuard per variant (no confirm-flow support --
        # matches the CLI's own `investment-committee compare`, which has no
        # --yes-style budget-override flag either).
        return asyncio.run(
            compare_committee_vs_single(
                portfolio,
                portfolio_id,
                fred_client,
                nbp_client,
                llm_client,
                prompt_registry,
                MODEL,
                committee_budget_usd,
                fx_client=fx_client,
            )
        )

    async def _run_committee_job(
        job_id: UUID, portfolio: Portfolio, portfolio_id: str, variant: str
    ) -> None:
        repository.update_committee_job_status(app.state.db.cursor(), job_id, "running")

        llm_client = llm_client_factory()
        fred_client = fred_client_factory()
        nbp_client = nbp_client_factory()
        fx_client = fx_client_factory()
        prompt_registry = app.state.prompt_registry

        budget = None
        if variant in ("single", "committee"):
            budget = BudgetGuard(
                budget_usd=committee_budget_usd,
                max_iterations=committee_max_iterations,
                on_budget_exceeded=_make_confirm_callback(job_id),
            )

        try:
            result = await asyncio.to_thread(
                _run_variant_sync,
                variant,
                portfolio,
                portfolio_id,
                fred_client,
                nbp_client,
                llm_client,
                prompt_registry,
                fx_client,
                budget,
            )
        except Exception as exc:
            # A job's failure must never crash this background task silently
            # -- it has to land in the job row, or the frontend would poll a
            # job stuck in "running" forever.
            repository.finish_committee_job(
                app.state.db.cursor(), job_id, status="failed", error=str(exc)
            )
            return

        repository.finish_committee_job(
            app.state.db.cursor(),
            job_id,
            status="done",
            cost_usd=_committee_result_cost(result),
            result_json=result.model_dump_json(),
        )

    return app


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


async def _instrument_values_by_key(
    connection: duckdb.DuckDBPyConnection, portfolio_id: UUID, fx_client: NbpFxClient
) -> dict[str, Decimal]:
    # Live, non-live-price-refreshed value on purpose -- aggregators sum
    # whatever the portfolio's positions already show (same stored value
    # metrics.py would use before #190's live-refresh, kept simple here:
    # an aggregate is a grouping/display concern, not itself a live quote).
    values: dict[str, Decimal] = {}
    for row in current_position_rows(connection, portfolio_id):
        position = position_row_to_domain(row)
        key = instrument_key(position)
        values[key] = values.get(key, Decimal(0)) + await base_currency_value(position, fx_client)
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


def _to_committee_job_out(row: repository.CommitteeJobRow) -> CommitteeJobOut:
    (
        job_id,
        _portfolio_id,
        _snapshot_id,
        variant,
        status,
        created_at,
        finished_at,
        _model,
        cost_usd,
        error,
        result_json,
    ) = row
    result: CommitteeReport | ComparisonReport | None = None
    if result_json is not None:
        result = (
            ComparisonReport.model_validate_json(result_json)
            if variant == "compare"
            else CommitteeReport.model_validate_json(result_json)
        )
    return CommitteeJobOut(
        job_id=job_id,
        variant=cast(CommitteeVariant, variant),
        status=cast(CommitteeJobStatus, status),
        created_at=created_at,
        finished_at=finished_at,
        cost_usd=cost_usd,
        error=error,
        result=result,
    )


def _committee_result_cost(result: CommitteeReport | ComparisonReport) -> Decimal:
    if isinstance(result, ComparisonReport):
        return result.single_agent.cost_usd + result.committee.cost_usd
    return result.cost_usd
