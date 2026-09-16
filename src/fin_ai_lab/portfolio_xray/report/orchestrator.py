from datetime import date
from decimal import Decimal

from fin_ai_lab.core.llm.client import LlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.portfolio_xray.canonical import AccountType, Position
from fin_ai_lab.portfolio_xray.identification.openfigi import OpenFigiClient
from fin_ai_lab.portfolio_xray.metrics.fx import NbpFxClient, convert_to_base_currency
from fin_ai_lab.portfolio_xray.metrics.price_history import fetch_price_history
from fin_ai_lab.portfolio_xray.metrics.risk import compute_risk_metrics
from fin_ai_lab.portfolio_xray.metrics.weights import compute_weights
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry
from fin_ai_lab.portfolio_xray.report.builder import build_report
from fin_ai_lab.portfolio_xray.report.models import InstrumentMetadata, MetricsJson
from fin_ai_lab.portfolio_xray.sectors.classifier import classify_sector
from fin_ai_lab.portfolio_xray.service import ApprovalCallback, import_file

BASE_CURRENCY = "PLN"  # matches canonical.Portfolio.base_currency (Literal["PLN"])


class ReportGenerationError(Exception):
    pass


async def generate_report(
    file_bytes: bytes,
    *,
    valuation_date: date,
    account_type: AccountType,
    market_currency: str,
    registry: ParserRegistry,
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    broker_hint: str | None = None,
    on_new_config_proposed: ApprovalCallback | None = None,
    openfigi_client: OpenFigiClient | None = None,
    broker_market: str | None = None,
    fx_client: NbpFxClient | None = None,
    benchmark_ticker: str | None = None,
) -> str:
    import_result = await import_file(
        file_bytes,
        valuation_date=valuation_date,
        account_type=account_type,
        market_currency=market_currency,
        registry=registry,
        broker_hint=broker_hint,
        llm_client=llm_client,
        prompt_registry=prompt_registry,
        model=model,
        on_new_config_proposed=on_new_config_proposed,
        openfigi_client=openfigi_client,
        broker_market=broker_market,
    )
    if import_result.errors:
        raise ReportGenerationError("; ".join(import_result.errors))

    fx_client = fx_client or NbpFxClient()
    positions_with_base_value = [
        (position, await _base_currency_value(position, valuation_date, fx_client))
        for position in import_result.positions
    ]
    try:
        weights = compute_weights(positions_with_base_value)
    except ValueError as exc:
        raise ReportGenerationError(str(exc)) from exc

    price_history_by_key: dict[str, object] = {}
    weight_by_key: dict[str, float] = {}
    instrument_metadata: dict[str, InstrumentMetadata] = {}
    category_weight: dict[str, Decimal] = {}

    for index, weighted in enumerate(weights.weighted_positions):
        key = str(index)
        position = weighted.position
        weight_by_key[key] = float(weighted.weight)

        # OpenFIGI's exchange ticker when resolved, else the broker's own
        # symbol as a best-effort fallback (known MVP limitation for
        # ISIN-less positions, e.g. XTB CFDs — 03-design.md P1-S3 note).
        ticker = position.ticker or position.symbol
        price_history_by_key[key] = fetch_price_history(ticker) if ticker else None

        category = await classify_sector(position, llm_client, prompt_registry, model)
        category_weight[category] = category_weight.get(category, Decimal(0)) + weighted.weight
        instrument_metadata[key] = InstrumentMetadata(
            name=position.instrument_name,
            category=category,
            exchange_code=position.exchange_code,
            currency=position.market_currency,
        )

    benchmark_history = fetch_price_history(benchmark_ticker) if benchmark_ticker else None
    risk = compute_risk_metrics(
        price_history_by_key=price_history_by_key,
        weight_by_key=weight_by_key,
        total_positions=len(import_result.positions),
        benchmark_history=benchmark_history,
    )

    metrics = MetricsJson(
        valuation_date=valuation_date,
        base_currency=BASE_CURRENCY,
        weights=weights,
        risk=risk,
        allocation_by_category=category_weight,
    )

    return await build_report(metrics, instrument_metadata, llm_client, prompt_registry, model)


async def _base_currency_value(
    position: Position, valuation_date: date, fx_client: NbpFxClient
) -> Decimal:
    if position.market_value is None or position.market_currency is None:
        return Decimal(0)
    return await convert_to_base_currency(
        position.market_value, position.market_currency, valuation_date, fx_client
    )
