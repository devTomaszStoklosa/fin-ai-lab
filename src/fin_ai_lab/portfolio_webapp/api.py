import asyncio
import threading
import zipfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date as date_type
from datetime import timedelta
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
from fin_ai_lab.core.errors import ResponseValidationError
from fin_ai_lab.core.llm.client import GeminiLlmClient, LlmClient
from fin_ai_lab.core.llm.embeddings import EmbeddingClient, GeminiEmbeddingClient
from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.llm.trace import TRACES_DIR, count_calls_today
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag.service import INDEX_PATH as FILINGS_INDEX_PATH
from fin_ai_lab.filings_rag.service import PROMPTS_DIR as FILINGS_RAG_PROMPTS_DIR
from fin_ai_lab.filings_rag.service import (
    AnswerRejectedError,
    SavedIndexCache,
    UnknownCompanyError,
    indexed_companies,
)
from fin_ai_lab.filings_rag.service import ask as ask_filings
from fin_ai_lab.investment_committee.service import (
    BudgetGuard,
    CommitteeReport,
    ComparisonReport,
    compare_committee_vs_single,
    run_committee,
    run_single_agent,
)
from fin_ai_lab.market_pulse.service import STATE_PATH as MARKET_PULSE_STATE_PATH
from fin_ai_lab.market_pulse.service import FredClient, NbpClient, classify_regime
from fin_ai_lab.market_pulse.service import ask as run_market_pulse_ask
from fin_ai_lab.market_pulse.service import load_previous as load_market_pulse_state
from fin_ai_lab.news_classifier.service import CORPUS_PATH as NEWS_CLASSIFIER_CORPUS_PATH
from fin_ai_lab.news_classifier.service import load_labeled as load_news_classifier_corpus
from fin_ai_lab.portfolio_webapp import db, repository
from fin_ai_lab.portfolio_webapp.aggregators import (
    Aggregator,
    CycleError,
    instrument_key,
    resolve_value,
    validate_no_cycle,
)
from fin_ai_lab.portfolio_webapp.benchmark import BENCHMARKS, normalize_ticker
from fin_ai_lab.portfolio_webapp.benchmark_builder import (
    BenchmarkNotFoundError,
    BenchmarkUnavailableError,
    build_benchmark,
)
from fin_ai_lab.portfolio_webapp.bossa_financial import (
    FinancialHistory,
    is_financial_history,
    parse_financial_history,
)
from fin_ai_lab.portfolio_webapp.breakdowns import (
    BUILTIN_ASSET_CLASS,
    BUILTIN_NAMES,
    BUILTIN_PREFIX,
    Breakdown,
    BreakdownError,
    validate_parent,
)
from fin_ai_lab.portfolio_webapp.cash_operations import (
    CashHistory,
    CashOperationsError,
    extract_xtb_cash_operations,
)
from fin_ai_lab.portfolio_webapp.closed_lots import ClosedLotsHistory, extract_xtb_closed_lots
from fin_ai_lab.portfolio_webapp.dividend_forecast_builder import (
    DividendsFetcher,
    build_dividend_forecast,
)
from fin_ai_lab.portfolio_webapp.dividends_builder import build_dividend_history
from fin_ai_lab.portfolio_webapp.instrument_overrides_builder import (
    UnknownYahooSymbolError,
    YahooUnavailableError,
    checked_override,
)
from fin_ai_lab.portfolio_webapp.instruments import Identities, asset_assignments
from fin_ai_lab.portfolio_webapp.instruments_builder import build_instruments, load_link_state
from fin_ai_lab.portfolio_webapp.lots import (
    OpenLot,
    extract_xtb_open_lots,
    lots_matching_quantity,
)
from fin_ai_lab.portfolio_webapp.manual_valuations import (
    ManualValuation,
    ValuationDateError,
    validate_purchase_date,
    validate_valuation_date,
)
from fin_ai_lab.portfolio_webapp.manual_valuations import (
    market_value as manual_market_value,
)
from fin_ai_lab.portfolio_webapp.repository import PortfolioRow, PositionRow, SnapshotRow
from fin_ai_lab.portfolio_webapp.schemas import (
    AggregatorCreate,
    AggregatorOut,
    AssignmentIn,
    BenchmarkOptionOut,
    BenchmarkOut,
    BreakdownCreate,
    BreakdownGroupIn,
    BreakdownGroupOut,
    BreakdownOut,
    BreakdownUpdate,
    CommitteeAnalysisRequest,
    CommitteeJobOut,
    ComparisonReportOut,
    ConfirmBudgetRequest,
    DividendForecastOut,
    DividendHistoryOut,
    FilingsAnswerOut,
    FilingsAskRequest,
    FilingsIndexOut,
    ImportResponse,
    InstrumentDetachIn,
    InstrumentLinkIn,
    InstrumentOwnerDataIn,
    InstrumentsOut,
    LlmUsageOut,
    ManualValuationIn,
    ManualValuationOut,
    MarketPulseAskOut,
    MarketPulseAskRequest,
    MarketPulseBriefOut,
    MarketPulseIndicatorsOut,
    MetricsOut,
    PortfolioCreate,
    PortfolioOut,
    PositionCreate,
    PositionOut,
    PositionPreviewOut,
    ProposePreview,
    ReportOut,
    SharesOut,
    SnapshotOut,
    ValuationOut,
)
from fin_ai_lab.portfolio_webapp.shares_builder import ALL_PORTFOLIOS_NAME, build_shares
from fin_ai_lab.portfolio_webapp.traded_instruments_builder import identify_missing_listings
from fin_ai_lab.portfolio_webapp.valuation import MissingFxRateError, fx_currency_code, fx_move
from fin_ai_lab.portfolio_webapp.valuation_builder import (
    DailyClosesFetcher,
    FxSeriesClient,
    build_valuation,
)
from fin_ai_lab.portfolio_webapp.yahoo_ticker import position_yahoo_ticker
from fin_ai_lab.portfolio_xray.canonical import AccountType, Portfolio, Position
from fin_ai_lab.portfolio_xray.identification.openfigi import OpenFigiClient
from fin_ai_lab.portfolio_xray.ledger import BossaTransaction, parse_bossa_csv
from fin_ai_lab.portfolio_xray.metrics.fx import NbpFxClient, convert_to_base_currency
from fin_ai_lab.portfolio_xray.metrics.price_history import (
    fetch_daily_closes,
    fetch_dividends,
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
from fin_ai_lab.portfolio_xray.service import build_bossa_import_result, import_file

BASE_CURRENCY = "PLN"  # matches canonical.Portfolio.base_currency (Literal["PLN"])

# Same default as the CLI (cli.py's `import` command) -- not exposed as a
# web UI option, this tool doesn't need model choice as a user-facing knob.
MODEL = "gemini-3.6-flash"

# Free-tier daily cap per model, RPD only (RPM is throttled transparently by
# GeminiLlmClient itself, #218 -- nothing to surface here). Values verified
# live via real 429s (docs/LLM-API.md), not guessed. gemini-embedding-2
# (#225's "Zapytaj raport", one call per question) has no entry: its only
# verified free-tier limit is per minute and counts texts, which
# GeminiEmbeddingClient already paces itself under; a daily cap for it was
# never observed, and an unverified number here would be a guess.
KNOWN_FREE_TIER_LIMITS: dict[str, int] = {"gemini-3.6-flash": 20}
# cwd-relative, same as cli.py's own prompt dirs -- both are always launched
# via `uv run` from the repo root. Not imported from cli.py: portfolio_webapp
# may only depend on core and portfolio_xray.service (docs/ARCHITECTURE.md
# rule 6), not on the CLI module.
PORTFOLIO_PROMPTS_DIR = Path("src/fin_ai_lab/portfolio_xray/parsers/prompts")
REPORT_PROMPTS_DIR = Path("src/fin_ai_lab/portfolio_xray/report/prompts")
SECTOR_PROMPTS_DIR = Path("src/fin_ai_lab/portfolio_xray/sectors/prompts")
MARKET_PULSE_PROMPTS_DIR = Path("src/fin_ai_lab/market_pulse/prompts")
# Read-only, generated by the scheduled task (scripts/market_pulse_register_task.ps1)
# -- this app never writes here, only shows the latest already-generated brief.
MARKET_PULSE_BRIEFS_DIR = Path("data/briefs")
# Checked-in artifact from `news-classifier compare-report` (P4-S7) -- this
# app only reads and displays it, never regenerates it (that needs real eval
# runs under evals/runs/, out of scope for a zero-cost display endpoint).
COMPARISON_REPORT_PATH = Path("docs/specs/p4-news-classifier/reports/p4-s7-comparison.md")
INVESTMENT_COMMITTEE_PROMPTS_DIR = Path("src/fin_ai_lab/investment_committee/prompts")
# Same defaults as cli.py's `investment-committee analyze`/`compare` commands
# -- not exposed as a user-tunable web option (#226 doesn't ask for one).
COMMITTEE_BUDGET_USD = Decimal("1.00")
COMMITTEE_MAX_ITERATIONS = 10
# How long a job waits for a POST .../confirm before treating the budget
# override as denied (BudgetGuard's own fail-safe-deny default) and failing
# the job -- so an abandoned browser tab never holds a worker thread forever.
CONFIRMATION_TIMEOUT_S = 900.0


def _default_llm_client() -> LlmClient:
    settings = Settings()
    if settings.gemini_api_key:
        return GeminiLlmClient(api_key=settings.gemini_api_key)
    return FakeLlmClient({})


def _fetch_daily_closes(ticker: str, start: date_type, refresh: bool) -> dict | None:
    return fetch_daily_closes(ticker, start, refresh=refresh)


def _fetch_adjusted_daily_closes(ticker: str, start: date_type, refresh: bool) -> dict | None:
    return fetch_daily_closes(ticker, start, refresh=refresh, adjusted=True)


def _default_embedding_client() -> EmbeddingClient | None:
    settings = Settings()
    if settings.gemini_api_key:
        return GeminiEmbeddingClient(api_key=settings.gemini_api_key)
    return None


def _default_fred_client() -> FredClient:
    return FredClient(Settings().require_fred_api_key())


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
        app.state.report_locks: dict[UUID, asyncio.Lock] = {}
        # #226: bridges a committee job's blocking BudgetGuard.on_budget_exceeded
        # callback (running in a worker thread, see _make_confirm_callback) to
        # the POST .../confirm endpoint (running on the main event loop).
        app.state.committee_confirmations: dict[UUID, threading.Event] = {}
        app.state.committee_confirmation_decisions: dict[UUID, bool] = {}
        # Keeps a strong reference to every in-flight job task -- asyncio
        # only guarantees a fire-and-forget task survives if something else
        # holds onto it, otherwise it can be garbage-collected mid-run.
        app.state.committee_job_tasks: set[asyncio.Task] = set()
        yield
        app.state.db.close()

    app = FastAPI(title="Portfel", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/llm-usage", response_model=list[LlmUsageOut])
    def llm_usage() -> list[LlmUsageOut]:
        calls_by_model = count_calls_today(traces_dir)
        return [
            LlmUsageOut(model=model, calls_today=calls_by_model.get(model, 0), rpd_limit=rpd_limit)
            for model, rpd_limit in KNOWN_FREE_TIER_LIMITS.items()
        ]

    @app.get("/api/market-pulse/brief/latest", response_model=MarketPulseBriefOut | None)
    def market_pulse_latest_brief() -> MarketPulseBriefOut | None:
        latest = _latest_brief_file(briefs_dir)
        if latest is None:
            return None
        brief_date, path = latest
        return MarketPulseBriefOut(date=brief_date, text=path.read_text(encoding="utf-8"))

    @app.get("/api/market-pulse/indicators", response_model=MarketPulseIndicatorsOut)
    def market_pulse_indicators() -> MarketPulseIndicatorsOut:
        indicators = load_market_pulse_state(market_pulse_state_path)
        regime = classify_regime(indicators)
        return MarketPulseIndicatorsOut(
            regime=regime.regime, regime_signals=regime.signals, indicators=indicators
        )

    @app.post("/api/market-pulse/ask", response_model=MarketPulseAskOut)
    async def market_pulse_ask(payload: MarketPulseAskRequest) -> MarketPulseAskOut:
        llm_client = llm_client_factory()
        prompt_registry = app.state.prompt_registry
        try:
            answer = await run_market_pulse_ask(
                payload.question,
                llm_client,
                prompt_registry,
                MODEL,
                fred_client_factory(),
                nbp_client_factory(),
            )
        except genai_errors.APIError as exc:
            raise _llm_unavailable(exc) from exc
        return MarketPulseAskOut(text=answer.text, tool_calls=answer.tool_calls)

    @app.get("/api/news-classifier/comparison-report", response_model=ComparisonReportOut | None)
    def news_classifier_comparison_report() -> ComparisonReportOut | None:
        if not comparison_report_path.exists():
            return None
        markdown = comparison_report_path.read_text(encoding="utf-8")
        columns, rows = _parse_markdown_table(markdown, "## Podsumowanie")
        notes = _parse_bullet_list(markdown, "## Klasy bez wsparcia w zbiorze testowym")

        corpus = load_news_classifier_corpus(news_classifier_corpus_path)
        latest_headline_date = max(
            (item.headline.published_at.date() for item in corpus), default=None
        )
        return ComparisonReportOut(
            columns=columns,
            rows=rows,
            zero_support_notes=notes,
            corpus_size=len(corpus),
            corpus_latest_headline_date=latest_headline_date,
        )

    @app.get("/api/filings-rag/companies", response_model=FilingsIndexOut)
    def filings_rag_companies() -> FilingsIndexOut:
        index = app.state.filings_index_cache.get()
        if index is None:
            return FilingsIndexOut(built_at=None, companies=[])
        return FilingsIndexOut(built_at=index.built_at, companies=indexed_companies(index))

    @app.post("/api/filings-rag/ask", response_model=FilingsAnswerOut)
    async def filings_rag_ask(payload: FilingsAskRequest) -> FilingsAnswerOut:
        index = app.state.filings_index_cache.get()
        if index is None:
            raise HTTPException(
                status_code=409,
                detail="Indeks raportów nie jest jeszcze zbudowany -- uruchom "
                "`uv run fin-ai-lab filings-rag build-index`.",
            )
        embedding_client = embedding_client_factory()
        if embedding_client is None:
            raise HTTPException(
                status_code=503, detail="Brak klucza GEMINI_API_KEY -- nie da się zadać pytania."
            )
        try:
            answer = await ask_filings(
                payload.question,
                index,
                company=payload.company,
                llm_client=llm_client_factory(),
                embedding_client=embedding_client,
                prompt_registry=app.state.prompt_registry,
                model=MODEL,
            )
        except UnknownCompanyError as exc:
            raise HTTPException(
                status_code=422, detail=f"Spółki {exc.company} nie ma w indeksie."
            ) from exc
        except genai_errors.APIError as exc:
            raise _llm_unavailable(exc) from exc
        except (AnswerRejectedError, ResponseValidationError) as exc:
            # REQ-020: a citation that isn't a verbatim excerpt of its source
            # is never shown -- the whole answer is withheld instead.
            raise HTTPException(
                status_code=502,
                detail="Model zwrócił odpowiedź, której cytatów nie dało się potwierdzić "
                "w źródle -- spróbuj ponownie albo zadaj pytanie inaczej.",
            ) from exc
        return FilingsAnswerOut(
            text=answer.text,
            refused=answer.refused,
            refusal_reason=answer.refusal_reason,
            citations=answer.citations,
        )

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

    @app.delete("/api/portfolios/{portfolio_id}", status_code=204)
    def delete_portfolio(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> None:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        repository.delete_portfolio(connection, portfolio_id)

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
        "/api/portfolios/{portfolio_id}/import/bossa",
        response_model=ImportResponse,
        status_code=201,
    )
    async def import_bossa_portfolio_file(
        portfolio_id: UUID,
        file: UploadFile = File(...),
        valuation_date: str = Form(...),
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
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
        openfigi_client = openfigi_client_factory()
        # Every traded ISIN, sold ones included, gets the listing the value
        # history prices it by (#277) -- held positions alone would leave
        # everything sold at a constant value.
        if openfigi_client is not None:
            injection_warnings = injection_warnings + await identify_missing_listings(
                connection, all_transactions, openfigi_client, quote_currency_fetcher
            )

        result = await build_bossa_import_result(
            all_transactions,
            account_type=_resolve_account_type(portfolio),
            valuation_date=parsed_date,
            openfigi_client=openfigi_client,
            # Bossa trades on the Warsaw Stock Exchange; "PW" is OpenFIGI's
            # real exchange code for it (same one already used for XTB's own
            # Polish listings), not a guess.
            broker_market="PW",
            quote_currency_fetcher=quote_currency_fetcher,
            fx_client=fx_client_factory(),
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
                live_values = await _live_market_values(
                    [_position_row_to_domain(p) for p in position_rows],
                    price_ratio_fetcher,
                    fx_client_factory(),
                    today_provider(),
                )
                positions = [
                    _to_position_out(p, live_market_value=live_value)
                    for p, live_value in zip(position_rows, live_values, strict=True)
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

        purchased_on = payload.purchased_on or today_provider()
        _check_dates(validate_purchase_date, purchased_on, [], today_provider())
        # Valued at cost on creation: no valuation exists yet (#288).
        position = await _build_manual_position(
            payload,
            account_type=_resolve_account_type(portfolio),
            market_value=manual_market_value(payload.quantity, payload.avg_cost, []),
            purchased_on=purchased_on,
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
        payload: PositionCreate,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> PositionOut:
        portfolio = _require_manual_position(connection, portfolio_id, position_id)
        stored = repository.get_position(connection, position_id)
        assert stored is not None
        valuations = repository.list_manual_valuations(connection, position_id)
        purchased_on = payload.purchased_on or stored[13]
        _check_dates(validate_purchase_date, purchased_on, valuations, today_provider())

        # The value follows the owner's valuations (#288), per unit -- a new
        # quantity scales it, a new purchase price matters only without one.
        position = await _build_manual_position(
            payload,
            account_type=_resolve_account_type(portfolio),
            market_value=manual_market_value(payload.quantity, payload.avg_cost, valuations),
            purchased_on=purchased_on,
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

    @app.get(
        "/api/portfolios/{portfolio_id}/positions/{position_id}/valuations",
        response_model=list[ManualValuationOut],
    )
    def list_manual_valuations(
        portfolio_id: UUID,
        position_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> list[ManualValuationOut]:
        _require_manual_position(connection, portfolio_id, position_id)
        position = repository.get_position(connection, position_id)
        assert position is not None
        return [
            _to_valuation_out(valuation, position[8])
            for valuation in repository.list_manual_valuations(connection, position_id)
        ]

    @app.put(
        "/api/portfolios/{portfolio_id}/positions/{position_id}/valuations/{valued_on}",
        response_model=ManualValuationOut,
    )
    def save_manual_valuation(
        portfolio_id: UUID,
        position_id: UUID,
        valued_on: date_type,
        payload: ManualValuationIn,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> ManualValuationOut:
        # PUT on the day itself: a second valuation of the same day replaces
        # the first, the same request twice changes nothing more (#288).
        _require_manual_position(connection, portfolio_id, position_id)
        position = repository.get_position(connection, position_id)
        assert position is not None
        _check_dates(validate_valuation_date, valued_on, position[13], today_provider())

        valuation = ManualValuation(valued_on=valued_on, unit_value=payload.unit_value)
        repository.save_manual_valuation(connection, position_id, valuation)
        _sync_manual_market_value(connection, position)
        return _to_valuation_out(valuation, position[8])

    @app.delete(
        "/api/portfolios/{portfolio_id}/positions/{position_id}/valuations/{valued_on}",
        status_code=204,
    )
    def delete_manual_valuation(
        portfolio_id: UUID,
        position_id: UUID,
        valued_on: date_type,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> None:
        _require_manual_position(connection, portfolio_id, position_id)
        position = repository.get_position(connection, position_id)
        assert position is not None
        valuations = repository.list_manual_valuations(connection, position_id)
        if all(valuation.valued_on != valued_on for valuation in valuations):
            raise HTTPException(status_code=404, detail="Valuation not found")

        repository.delete_manual_valuation(connection, position_id, valued_on)
        _sync_manual_market_value(connection, position)

    @app.get("/api/portfolios/{portfolio_id}/metrics", response_model=MetricsOut)
    async def get_metrics(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> MetricsOut:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        rows = _current_position_rows(connection, portfolio_id)
        fx_client = fx_client_factory()
        positions = [_position_row_to_domain(row) for row in rows]
        live_values = await _live_market_values(
            positions, price_ratio_fetcher, fx_client, today_provider()
        )
        positions_with_base_value = []
        for position, live_value in zip(positions, live_values, strict=True):
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
                key: _as_percent(value) for key, value in weights.allocation_by_asset_class.items()
            },
            allocation_by_currency={
                key: _as_percent(value) for key, value in weights.allocation_by_currency.items()
            },
        )

    @app.get("/api/valuation", response_model=ValuationOut)
    async def get_all_portfolios_valuation(
        refresh: bool = False,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> ValuationOut:
        # Every portfolio on one day axis -- the start page's sum and chart.
        return await build_valuation(
            connection,
            repository.list_portfolios(connection),
            today=today_provider(),
            refresh=refresh,
            closes_fetcher=daily_closes_fetcher,
            fx_client=fx_client_factory(),
        )

    @app.get("/api/portfolios/{portfolio_id}/valuation", response_model=ValuationOut)
    async def get_portfolio_valuation(
        portfolio_id: UUID,
        refresh: bool = False,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> ValuationOut:
        portfolio = repository.get_portfolio(connection, portfolio_id)
        if portfolio is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        return await build_valuation(
            connection,
            [portfolio],
            today=today_provider(),
            refresh=refresh,
            closes_fetcher=daily_closes_fetcher,
            fx_client=fx_client_factory(),
        )

    @app.get("/api/benchmarks", response_model=list[BenchmarkOptionOut])
    def list_benchmarks() -> list[BenchmarkOptionOut]:
        return [
            BenchmarkOptionOut(id=b.id, label=b.label, ticker=b.ticker, note=b.note)
            for b in BENCHMARKS
        ]

    # #273: asked for only when the chart's comparison mode is open -- no
    # Yahoo lookup for a benchmark nobody looks at. `start` is the
    # valuation's first day, so both series share one day axis.
    @app.get("/api/benchmark", response_model=BenchmarkOut)
    async def get_benchmark(ticker: str, start: date_type, refresh: bool = False) -> BenchmarkOut:
        normalized = normalize_ticker(ticker)
        if normalized is None:
            raise HTTPException(
                status_code=422,
                detail="Nieprawidłowy ticker -- dozwolone litery, cyfry i znaki . ^ = -",
            )
        try:
            return await build_benchmark(
                normalized,
                start=start,
                today=today_provider(),
                refresh=refresh,
                closes_fetcher=benchmark_closes_fetcher,
                quote_currency_fetcher=quote_currency_fetcher,
                fx_client=fx_client_factory(),
            )
        except BenchmarkNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"Yahoo nie zna tickera {normalized} albo nie ma jego historii.",
            ) from None
        except BenchmarkUnavailableError:
            raise HTTPException(
                status_code=502, detail="Yahoo nie odpowiedziało -- spróbuj ponownie za chwilę."
            ) from None
        except MissingFxRateError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Brak kursu NBP dla {exc.currency} -- nie da się przeliczyć "
                f"{normalized} na PLN.",
            ) from None

    @app.get("/api/dividends/history", response_model=DividendHistoryOut)
    async def get_all_portfolios_dividend_history(
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> DividendHistoryOut:
        # #265: every portfolio together -- the start page's dividends card.
        return await build_dividend_history(
            connection,
            repository.list_portfolios(connection),
            today=today_provider(),
            fx_client=fx_client_factory(),
        )

    @app.get("/api/portfolios/{portfolio_id}/dividends/history", response_model=DividendHistoryOut)
    async def get_portfolio_dividend_history(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> DividendHistoryOut:
        portfolio = repository.get_portfolio(connection, portfolio_id)
        if portfolio is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        return await build_dividend_history(
            connection, [portfolio], today=today_provider(), fx_client=fx_client_factory()
        )

    async def _dividend_forecast(
        connection: duckdb.DuckDBPyConnection, portfolio_rows: list[PortfolioRow]
    ) -> DividendForecastOut:
        return await build_dividend_forecast(
            connection,
            portfolio_rows,
            today=today_provider(),
            fx_client=fx_client_factory(),
            dividends_fetcher=dividends_fetcher,
            quote_currency_fetcher=quote_currency_fetcher,
            closes_fetcher=daily_closes_fetcher,
        )

    # #266: separate from the history -- it asks Yahoo and takes longer,
    # while the history comes from the database alone and shows at once.
    @app.get("/api/dividends/forecast", response_model=DividendForecastOut)
    async def get_all_portfolios_dividend_forecast(
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> DividendForecastOut:
        return await _dividend_forecast(connection, repository.list_portfolios(connection))

    @app.get(
        "/api/portfolios/{portfolio_id}/dividends/forecast", response_model=DividendForecastOut
    )
    async def get_portfolio_dividend_forecast(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> DividendForecastOut:
        portfolio = repository.get_portfolio(connection, portfolio_id)
        if portfolio is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        return await _dividend_forecast(connection, [portfolio])

    @app.get("/api/breakdowns", response_model=list[BreakdownOut])
    def list_breakdowns(
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> list[BreakdownOut]:
        identities = load_link_state(connection).identities
        return [_to_breakdown_out(b, identities) for b in repository.list_breakdowns(connection)]

    @app.post("/api/breakdowns", response_model=BreakdownOut, status_code=201)
    def create_breakdown(
        payload: BreakdownCreate,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> BreakdownOut:
        return _to_breakdown_out(
            repository.create_breakdown(connection, name=payload.name), _identities(connection)
        )

    @app.put("/api/breakdowns/{breakdown_id}", response_model=BreakdownOut)
    def update_breakdown(
        breakdown_id: UUID,
        payload: BreakdownUpdate,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> BreakdownOut:
        _require_breakdown(connection, breakdown_id)
        updated = repository.update_breakdown(
            connection, breakdown_id=breakdown_id, name=payload.name, is_default=payload.is_default
        )
        return _to_breakdown_out(updated, _identities(connection))

    @app.delete("/api/breakdowns/{breakdown_id}", status_code=204)
    def delete_breakdown(
        breakdown_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> None:
        _require_breakdown(connection, breakdown_id)
        repository.delete_breakdown(connection, breakdown_id)

    @app.post(
        "/api/breakdowns/{breakdown_id}/duplicate", response_model=BreakdownOut, status_code=201
    )
    def duplicate_breakdown(
        breakdown_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> BreakdownOut:
        source = _require_breakdown(connection, breakdown_id)
        name = f"{source.name} (kopia)"[:100]
        duplicated = repository.duplicate_breakdown(connection, source, name=name)
        return _to_breakdown_out(duplicated, _identities(connection))

    @app.post("/api/breakdowns/{breakdown_id}/groups", response_model=BreakdownOut, status_code=201)
    def create_breakdown_group(
        breakdown_id: UUID,
        payload: BreakdownGroupIn,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> BreakdownOut:
        breakdown = _require_breakdown(connection, breakdown_id)
        _validate_parent(None, payload.parent_id, breakdown)
        repository.create_breakdown_group(
            connection, breakdown_id=breakdown_id, name=payload.name, parent_id=payload.parent_id
        )
        return _to_breakdown_out(
            _require_breakdown(connection, breakdown_id), _identities(connection)
        )

    @app.put("/api/breakdowns/{breakdown_id}/groups/{group_id}", response_model=BreakdownOut)
    def update_breakdown_group(
        breakdown_id: UUID,
        group_id: UUID,
        payload: BreakdownGroupIn,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> BreakdownOut:
        breakdown = _require_breakdown(connection, breakdown_id)
        _require_group(breakdown, group_id)
        _validate_parent(group_id, payload.parent_id, breakdown)
        repository.update_breakdown_group(
            connection, group_id=group_id, name=payload.name, parent_id=payload.parent_id
        )
        return _to_breakdown_out(
            _require_breakdown(connection, breakdown_id), _identities(connection)
        )

    @app.delete("/api/breakdowns/{breakdown_id}/groups/{group_id}", response_model=BreakdownOut)
    def delete_breakdown_group(
        breakdown_id: UUID,
        group_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> BreakdownOut:
        breakdown = _require_breakdown(connection, breakdown_id)
        _require_group(breakdown, group_id)
        repository.delete_breakdown_group(connection, breakdown, group_id)
        return _to_breakdown_out(
            _require_breakdown(connection, breakdown_id), _identities(connection)
        )

    @app.put("/api/breakdowns/{breakdown_id}/assignments", response_model=BreakdownOut)
    def set_breakdown_assignment(
        breakdown_id: UUID,
        payload: AssignmentIn,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> BreakdownOut:
        breakdown = _require_breakdown(connection, breakdown_id)
        if payload.group_id is not None and all(g.id != payload.group_id for g in breakdown.groups):
            raise HTTPException(status_code=422, detail="Grupa nie należy do tego podziału.")
        # Stored under the asset key (S12); the same asset's other member
        # keys lose what they held -- the owner just placed the whole asset.
        identities = _identities(connection)
        asset_key = identities.asset_key(payload.instrument_key)
        repository.set_assignment(
            connection,
            breakdown_id=breakdown_id,
            instrument_key=asset_key,
            group_id=payload.group_id,
            replaces=tuple(k for k in identities.members(asset_key) if k != asset_key),
        )
        return _to_breakdown_out(_require_breakdown(connection, breakdown_id), identities)

    @app.get("/api/shares", response_model=SharesOut)
    async def get_shares(
        breakdown: str = BUILTIN_ASSET_CLASS,
        portfolio_id: UUID | None = None,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> SharesOut:
        # One portfolio, or every portfolio when portfolio_id is left out --
        # the same two scopes as the valuation endpoints.
        if portfolio_id is not None:
            portfolio = repository.get_portfolio(connection, portfolio_id)
            if portfolio is None:
                raise HTTPException(status_code=404, detail="Portfolio not found")
            rows, root_name = [portfolio], portfolio[1]
        else:
            rows, root_name = repository.list_portfolios(connection), ALL_PORTFOLIOS_NAME

        builtin, stored = None, None
        if breakdown.startswith(BUILTIN_PREFIX):
            if breakdown not in BUILTIN_NAMES:
                raise HTTPException(status_code=422, detail=f"Nieznany podział: {breakdown}")
            builtin = breakdown
        else:
            try:
                breakdown_id = UUID(breakdown)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422, detail=f"Nieznany podział: {breakdown}"
                ) from exc
            stored = _require_breakdown(connection, breakdown_id)

        return await build_shares(
            connection,
            rows,
            builtin=builtin,
            breakdown=stored,
            root_name=root_name,
            today=today_provider(),
            closes_fetcher=daily_closes_fetcher,
            fx_client=fx_client_factory(),
        )

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
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> InstrumentsOut:
        return await instruments_out(connection)

    @app.post("/api/instruments/links", response_model=InstrumentsOut)
    async def decide_instrument_link(
        payload: InstrumentLinkIn,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
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
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
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
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
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

    @app.post(
        "/api/portfolios/{portfolio_id}/committee-analysis",
        response_model=CommitteeJobOut,
    )
    async def start_committee_analysis(
        portfolio_id: UUID,
        payload: CommitteeAnalysisRequest,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
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

        rows = _current_position_rows(connection, portfolio_id)
        positions = [_position_row_to_domain(row) for row in rows]
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
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
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
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
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


def _check_dates(rule: Callable[..., None], *args: object) -> None:
    # A date the owner can fix (#288) -- 422 with the rule's own message.
    try:
        rule(*args)
    except ValuationDateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _sync_manual_market_value(connection: duckdb.DuckDBPyConnection, position: PositionRow) -> None:
    # After a valuation changed: the stored value follows the latest one,
    # else the purchase price (#288).
    valuations = repository.list_manual_valuations(connection, position[0])
    repository.set_market_value(
        connection, position[0], manual_market_value(position[8], position[9], valuations)
    )


def _to_valuation_out(valuation: ManualValuation, quantity: Decimal) -> ManualValuationOut:
    return ManualValuationOut(
        valued_on=valuation.valued_on,
        unit_value=valuation.unit_value,
        value=(quantity * valuation.unit_value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    )


async def _build_manual_position(
    payload: PositionCreate,
    *,
    account_type: str,
    market_value: Decimal,
    purchased_on: date_type,
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
        valuation_date=purchased_on,
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
        snapshot=_to_snapshot_out(snapshot_row, [_to_position_out(p) for p in position_rows]),
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


# Margin before an import date for its NBP rate: an import made on a
# weekend or holiday is valued at the last rate published before it.
_LIVE_FX_LOOKBACK = timedelta(days=10)


async def _live_market_values(
    positions: list[Position],
    price_ratio_fetcher: Callable[[str, date_type], Decimal | None],
    fx_client: FxSeriesClient,
    today: date_type,
) -> list[Decimal | None]:
    # Price ratios first, exchange rates second: NBP is only asked about the
    # currencies of positions that got a live price, once per request (#283).
    ratios = [await _live_price_ratio(position, price_ratio_fetcher) for position in positions]
    priced = [
        position for position, ratio in zip(positions, ratios, strict=True) if ratio is not None
    ]
    fx_rates = await _live_fx_rates(priced, fx_client, today)
    return [
        None if ratio is None else _live_market_value(position, ratio, fx_rates, today)
        for position, ratio in zip(positions, ratios, strict=True)
    ]


def _live_market_value(
    position: Position,
    ratio: Decimal,
    fx_rates: dict[str, dict[date_type, Decimal]],
    today: date_type,
) -> Decimal:
    # The price ratio applied to the already-stored (already-correct-
    # currency) value -- the quote's own unit is never taken as the
    # account's currency (#188). A listing quoted in another currency also
    # moves with that currency's exchange rate since the import (#283),
    # the same factor as the day-by-day valuation's.
    assert position.market_value is not None  # _live_price_ratio checked it
    value = position.market_value * ratio * _live_fx_move(position, fx_rates, today)
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _live_fx_move(
    position: Position, fx_rates: dict[str, dict[date_type, Decimal]], today: date_type
) -> Decimal:
    if position.market_currency is None:
        return Decimal(1)
    try:
        return fx_move(
            position.market_currency,
            position.quote_currency,
            position.valuation_date,
            today,
            fx_rates,
        )
    except MissingFxRateError:
        # No NBP rates for the currency (see _live_fx_rates): only the
        # exchange-rate factor is left out, the price move still counts --
        # the same rule as valuation.unit_value_series.
        return Decimal(1)


async def _live_fx_rates(
    positions: list[Position], fx_client: FxSeriesClient, today: date_type
) -> dict[str, dict[date_type, Decimal]]:
    # One NBP series per currency an exchange-rate factor needs. Same call
    # as the day-by-day valuation's, so both share its on-disk cache and
    # agree on today's rate. A currency NBP has no rates for, or a failed
    # request, is simply left out.
    start_by_currency: dict[str, date_type] = {}
    for position in positions:
        start = position.valuation_date - _LIVE_FX_LOOKBACK
        for currency in _fx_move_currencies(position):
            start_by_currency[currency] = min(start_by_currency.get(currency, start), start)

    fx_rates: dict[str, dict[date_type, Decimal]] = {}
    for currency, start in start_by_currency.items():
        try:
            fx_rates[currency] = await fx_client.mid_rate_series(currency, start, today)
        except Exception:
            # NBP down, or no table A/B rate for the currency -- a live
            # value must still come back, moved by its price alone.
            continue
    return fx_rates


def _fx_move_currencies(position: Position) -> set[str]:
    if position.market_currency is None or position.quote_currency is None:
        return set()
    quote_code = fx_currency_code(position.quote_currency)
    if quote_code == position.market_currency:
        return set()
    return {quote_code, position.market_currency} - {BASE_CURRENCY}


async def _live_price_ratio(
    position: Position, price_ratio_fetcher: Callable[[str, date_type], Decimal | None]
) -> Decimal | None:
    # Ratio of latest close to the close on the position's own valuation
    # date. Manual positions are the owner's own explicit input, left
    # untouched.
    if position.broker == repository.MANUAL_BROKER:
        return None
    if position.market_value is None or position.quantity <= 0:
        return None
    yfinance_ticker = position_yahoo_ticker(
        broker=position.broker,
        symbol=position.symbol,
        ticker=position.ticker,
        exchange_code=position.exchange_code,
    )
    if yfinance_ticker is None:
        return None

    try:
        return await asyncio.to_thread(
            price_ratio_fetcher, yfinance_ticker, position.valuation_date
        )
    except Exception:
        # yfinance is unofficial and sometimes blocked (docs/DATA-SOURCES.md)
        # -- a live-refresh failure must fall back to the stored value, never
        # break the page.
        return None


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
    return repository.row_to_position(row)


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


def _require_breakdown(connection: duckdb.DuckDBPyConnection, breakdown_id: UUID) -> Breakdown:
    breakdown = repository.get_breakdown(connection, breakdown_id)
    if breakdown is None:
        raise HTTPException(status_code=404, detail="Breakdown not found")
    return breakdown


def _require_group(breakdown: Breakdown, group_id: UUID) -> None:
    if all(group.id != group_id for group in breakdown.groups):
        raise HTTPException(status_code=404, detail="Group not found")


def _validate_parent(group_id: UUID | None, parent_id: UUID | None, breakdown: Breakdown) -> None:
    try:
        validate_parent(group_id, parent_id, breakdown.groups)
    except BreakdownError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _identities(connection: duckdb.DuckDBPyConnection) -> Identities:
    return load_link_state(connection).identities


def _to_breakdown_out(breakdown: Breakdown, identities: Identities) -> BreakdownOut:
    # Keyed by asset (S12), the same keys the shares tree uses.
    return BreakdownOut(
        id=breakdown.id,
        name=breakdown.name,
        is_default=breakdown.is_default,
        groups=[
            BreakdownGroupOut(
                id=group.id, name=group.name, parent_id=group.parent_id, position=group.position
            )
            for group in breakdown.groups
        ],
        assignments=asset_assignments(breakdown.assignments, identities),
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


def _latest_brief_file(briefs_dir: Path) -> tuple[date_type, Path] | None:
    if not briefs_dir.exists():
        return None
    dated_files = []
    for path in briefs_dir.glob("*.md"):
        try:
            brief_date = date_type.fromisoformat(path.stem)
        except ValueError:
            continue
        dated_files.append((brief_date, path))
    if not dated_files:
        return None
    return max(dated_files, key=lambda item: item[0])


def _parse_markdown_table(markdown: str, heading: str) -> tuple[list[str], list[list[str]]]:
    """Generic pipe-table extractor -- doesn't hardcode column names, so a
    future column added to `comparison_report.render_comparison_report()`
    shows up here without a code change."""
    lines = markdown.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == heading) + 1
    except StopIteration:
        return [], []

    table_lines = []
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped:
            if table_lines:
                break
            continue
        if stripped.startswith("|"):
            table_lines.append(stripped)
        elif table_lines:
            break
    if len(table_lines) < 2:
        return [], []

    def cells(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip("|").split("|")]

    columns = cells(table_lines[0])
    rows = [cells(line) for line in table_lines[2:]]  # table_lines[1] is the "|---|" separator
    return columns, rows


def _parse_bullet_list(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == heading) + 1
    except StopIteration:
        return []

    notes = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("- "):
            notes.append(stripped[2:])
        elif notes:
            break
    return notes


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
        variant=variant,
        status=status,
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
