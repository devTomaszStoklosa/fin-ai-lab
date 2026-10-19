"""The dependencies create_app() injects, bundled so each router can take them."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal
from pathlib import Path

from fin_ai_lab.core.llm.client import CostTrackingLlmClient
from fin_ai_lab.core.llm.embeddings import EmbeddingClient
from fin_ai_lab.market_pulse.service import FredClient, NbpClient
from fin_ai_lab.portfolio_webapp.dividend_forecast_builder import DividendsFetcher
from fin_ai_lab.portfolio_webapp.valuation_builder import DailyClosesFetcher
from fin_ai_lab.portfolio_xray.identification.openfigi import OpenFigiClient
from fin_ai_lab.portfolio_xray.metrics.fx import NbpFxClient
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry


@dataclass(frozen=True)
class AppDeps:
    """Everything create_app() lets a caller replace (clients, fetchers, paths).

    Production passes the real ones, tests pass fakes. A router reads only the
    fields it needs.
    """

    openfigi_client_factory: Callable[[], OpenFigiClient | None]
    llm_client_factory: Callable[[], CostTrackingLlmClient]
    parser_registry_factory: Callable[[], ParserRegistry]
    fx_client_factory: Callable[[], NbpFxClient]
    price_ratio_fetcher: Callable[[str, date_type], Decimal | None]
    quote_currency_fetcher: Callable[[str], str | None]
    traces_dir: Path
    briefs_dir: Path
    market_pulse_state_path: Path
    fred_client_factory: Callable[[], FredClient]
    nbp_client_factory: Callable[[], NbpClient]
    comparison_report_path: Path
    embedding_client_factory: Callable[[], EmbeddingClient | None]
    news_classifier_corpus_path: Path
    committee_budget_usd: Decimal
    committee_max_iterations: int
    daily_closes_fetcher: DailyClosesFetcher
    today_provider: Callable[[], date_type]
    dividends_fetcher: DividendsFetcher
    benchmark_closes_fetcher: DailyClosesFetcher
