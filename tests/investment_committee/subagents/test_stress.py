from datetime import date
from decimal import Decimal

from fin_ai_lab.investment_committee.subagents.stress import (
    DEFAULT_SCENARIOS,
    compute_stress_scenarios,
    run_stress_brief,
)
from fin_ai_lab.portfolio_xray.canonical import Portfolio, Position
from fin_ai_lab.portfolio_xray.metrics.weights import compute_weights


class _FakeFxClient:
    async def mid_rate(self, currency: str, as_of):
        return Decimal(1) if currency == "PLN" else Decimal("4.0")


def _portfolio() -> Portfolio:
    return Portfolio(
        valuation_date=date(2026, 9, 17),
        positions=[
            Position(
                broker="xtb", account_type="regular", instrument_name="Orlen",
                asset_class="equity", quantity=Decimal("10"),
                market_value=Decimal("1000"), market_currency="PLN",
                valuation_date=date(2026, 9, 17),
            ),
            Position(
                broker="xtb", account_type="regular", instrument_name="Bond fund",
                asset_class="bond", quantity=Decimal("1"),
                market_value=Decimal("1000"), market_currency="PLN",
                valuation_date=date(2026, 9, 17),
            ),
        ],
    )


def test_compute_stress_scenarios_is_a_pure_function_over_weights() -> None:
    weights = compute_weights([(_portfolio().positions[0], Decimal("1000"))])

    scenarios = compute_stress_scenarios(
        weights, [{"name": "test", "shock": {"equity": Decimal("-0.20")}}]
    )

    assert scenarios[0].portfolio_impact == Decimal("-200.00")


def test_compute_stress_scenarios_ignores_buckets_absent_from_the_shock() -> None:
    weights = compute_weights(
        [(_portfolio().positions[0], Decimal("1000")), (_portfolio().positions[1], Decimal("1000"))]
    )

    scenarios = compute_stress_scenarios(
        weights, [{"name": "equity only", "shock": {"equity": Decimal("-0.20")}}]
    )

    # Half the portfolio is "bond", not shocked here, so only the equity half moves.
    assert scenarios[0].portfolio_impact == Decimal("-200.00")


async def test_run_stress_brief_makes_no_llm_call_and_reports_default_scenario() -> None:
    brief = await run_stress_brief(_portfolio(), _FakeFxClient())

    assert brief.perspective == "stress"
    assert brief.confidence == 1.0
    assert len(brief.claims) == len(DEFAULT_SCENARIOS)
    assert all(claim.source_type == "computed_metric" for claim in brief.claims)
    assert "PLN" in brief.conclusion
