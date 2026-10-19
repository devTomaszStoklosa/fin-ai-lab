from datetime import date
from decimal import Decimal

from fin_ai_lab.core.evals.models import RunContext
from fin_ai_lab.portfolio_xray.canonical import Position
from fin_ai_lab.portfolio_xray.metrics.risk import RiskMetrics
from fin_ai_lab.portfolio_xray.metrics.weights import WeightedPosition, WeightMetrics
from fin_ai_lab.portfolio_xray.report.builder import ReportRejectedError, build_report
from fin_ai_lab.portfolio_xray.report.models import InstrumentMetadata, MetricsJson

# No estimate() here on purpose: both p1-report-faithfulness and p1-no-advice
# make a real narrative-writing LLM call, so their cost is genuinely unknown
# ahead of time — same reasoning as sector_target.py.

_VALUATION_DATE = date(2026, 9, 15)


def _position(name: str, symbol: str, asset_class: str) -> Position:
    return Position(
        broker="test",
        account_type="regular",
        instrument_name=name,
        symbol=symbol,
        asset_class=asset_class,
        quantity=Decimal("1"),
        market_currency="PLN",
        valuation_date=_VALUATION_DATE,
    )


def _fixture(name: str) -> tuple[MetricsJson, dict[str, InstrumentMetadata]]:
    if name == "diversified":
        weights = WeightMetrics(
            weighted_positions=[
                WeightedPosition(
                    position=_position("Apple Inc", "AAPL", "equity"),
                    weight=Decimal("0.5"),
                    base_currency_value=Decimal("5000"),
                ),
                WeightedPosition(
                    position=_position("MSCI World", "IWDA.UK", "etf"),
                    weight=Decimal("0.5"),
                    base_currency_value=Decimal("5000"),
                ),
            ],
            allocation_by_asset_class={"equity": Decimal("0.5"), "etf": Decimal("0.5")},
            allocation_by_currency={"PLN": Decimal("1")},
            allocation_by_account_type={"regular": Decimal("1")},
            hhi=Decimal("0.5"),
            effective_positions=Decimal("2"),
            top5_share=Decimal("1"),
        )
        risk = RiskMetrics(coverage=0.0, covered_positions=0, total_positions=2)
        metadata = {
            "0": InstrumentMetadata(name="Apple Inc", category="Technology", currency="PLN"),
            "1": InstrumentMetadata(name="MSCI World", category="ETF/fund", currency="PLN"),
        }
        allocation_by_category = {"Technology": Decimal("0.5"), "ETF/fund": Decimal("0.5")}

    elif name == "concentrated":
        weights = WeightMetrics(
            weighted_positions=[
                WeightedPosition(
                    position=_position("Tesla Inc", "TSLA", "equity"),
                    weight=Decimal("0.9"),
                    base_currency_value=Decimal("9000"),
                ),
                WeightedPosition(
                    position=_position("US Treasury Bond 20+yr", "GOVT", "bond"),
                    weight=Decimal("0.1"),
                    base_currency_value=Decimal("1000"),
                ),
            ],
            allocation_by_asset_class={"equity": Decimal("0.9"), "bond": Decimal("0.1")},
            allocation_by_currency={"PLN": Decimal("1")},
            allocation_by_account_type={"regular": Decimal("1")},
            hhi=Decimal("0.82"),
            effective_positions=Decimal("1.22"),
            top5_share=Decimal("1"),
        )
        risk = RiskMetrics(
            coverage=1.0,
            covered_positions=2,
            total_positions=2,
            annualized_volatility=0.35,
            var_95_1d=0.04,
            max_drawdown=0.22,
            beta=1.4,
        )
        metadata = {
            "0": InstrumentMetadata(name="Tesla Inc", category="Consumer", currency="PLN"),
            "1": InstrumentMetadata(
                name="US Treasury Bond 20+yr", category="bond", currency="PLN"
            ),
        }
        allocation_by_category = {"Consumer": Decimal("0.9"), "bond": Decimal("0.1")}

    else:
        raise ValueError(f"Unknown fixture '{name}'")

    metrics = MetricsJson(
        valuation_date=_VALUATION_DATE,
        base_currency="PLN",
        weights=weights,
        risk=risk,
        allocation_by_category=allocation_by_category,
    )
    return metrics, metadata


async def target(case_input: dict, ctx: RunContext) -> dict:
    metrics, metadata = _fixture(case_input["fixture"])
    model = ctx.model or "gemini-2.5-flash"

    try:
        text = await build_report(metrics, metadata, ctx.llm_client, ctx.prompts, model)
        mismatches: list[str] = []
    except ReportRejectedError as exc:
        # Graded via the "mismatches" field for p1-report-faithfulness. For
        # p1-no-advice this loses the actual (rejected) narrative text, so a
        # report rejected for numbers would trivially pass the no-advice
        # graders too — an accepted gap for this lab-scale eval.
        text = str(exc)
        mismatches = exc.mismatches

    return {"text": text, "mismatches": mismatches}
