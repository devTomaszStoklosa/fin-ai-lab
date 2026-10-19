from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date as date_type
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI

from fin_ai_lab.core.llm.client import CostTrackingLlmClient
from fin_ai_lab.core.llm.embeddings import EmbeddingClient
from fin_ai_lab.core.llm.trace import TRACES_DIR
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag.service import INDEX_PATH as FILINGS_INDEX_PATH
from fin_ai_lab.filings_rag.service import PROMPTS_DIR as FILINGS_RAG_PROMPTS_DIR
from fin_ai_lab.filings_rag.service import SavedIndexCache
from fin_ai_lab.market_pulse.service import STATE_PATH as MARKET_PULSE_STATE_PATH
from fin_ai_lab.market_pulse.service import FredClient, NbpClient
from fin_ai_lab.news_classifier.service import CORPUS_PATH as NEWS_CLASSIFIER_CORPUS_PATH
from fin_ai_lab.portfolio_webapp import db
from fin_ai_lab.portfolio_webapp.api import (
    aggregators,
    benchmark,
    breakdowns,
    committee,
    dividends,
    filings_rag,
    imports,
    instruments,
    market_pulse,
    metrics,
    news_classifier,
    portfolios,
    positions,
    report,
    shares,
    system,
    valuation,
)
from fin_ai_lab.portfolio_webapp.api.defaults import (
    COMMITTEE_BUDGET_USD,
    COMMITTEE_MAX_ITERATIONS,
    COMPARISON_REPORT_PATH,
    INVESTMENT_COMMITTEE_PROMPTS_DIR,
    MARKET_PULSE_BRIEFS_DIR,
    MARKET_PULSE_PROMPTS_DIR,
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
from fin_ai_lab.portfolio_webapp.dividend_forecast_builder import DividendsFetcher
from fin_ai_lab.portfolio_webapp.valuation_builder import DailyClosesFetcher
from fin_ai_lab.portfolio_xray.identification.openfigi import OpenFigiClient
from fin_ai_lab.portfolio_xray.metrics.fx import NbpFxClient
from fin_ai_lab.portfolio_xray.metrics.price_history import (
    fetch_dividends,
    fetch_quote_currency,
    price_change_ratio,
)
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry


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
        instruments,
        aggregators,
        report,
        committee,
    ):
        app.include_router(build.build_router(deps))

    return app
