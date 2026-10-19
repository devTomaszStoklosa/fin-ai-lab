from decimal import Decimal

from fin_ai_lab.investment_committee.models import Brief, Claim, StressScenario
from fin_ai_lab.portfolio_xray.canonical import Portfolio
from fin_ai_lab.portfolio_xray.metrics.fx import NbpFxClient, convert_to_base_currency
from fin_ai_lab.portfolio_xray.metrics.weights import WeightMetrics, compute_weights

# ASSUMPTION (03-design.md REQ-030 / 01-story.md AC-6's illustrative example
# only, not a real risk model): a shock keyed by an asset class ("equity")
# or a currency code ("PLN") is a direct percentage change applied to that
# bucket's share of the portfolio's base-currency value. "etf"/"fund" get
# the same shock as "equity" (no look-through to underlying holdings — same
# simplification weights.py already makes). The +200bp rate shock is
# pre-translated into an assumed ~4-year-duration price impact on "bond"
# positions, not computed from real duration data (01-story.md's "yfinance,
# tylko lokalnie" risk is about a richer version of this than the MVP needs).
DEFAULT_SCENARIOS: list[dict] = [
    {
        "name": "Akcje -20%, stopy +200pb, PLN -15%",
        "shock": {
            "equity": Decimal("-0.20"),
            "etf": Decimal("-0.20"),
            "fund": Decimal("-0.20"),
            "bond": Decimal("-0.08"),
            "PLN": Decimal("-0.15"),
        },
    },
]


def compute_stress_scenarios(
    weights: WeightMetrics, scenarios: list[dict] = DEFAULT_SCENARIOS
) -> list[StressScenario]:
    """P5-S3, REQ-030: pure function, no LLM call, no network — every
    scenario's impact comes from already-computed portfolio weights, never
    from a number the model generated."""
    total_value = sum(
        (position.base_currency_value for position in weights.weighted_positions), Decimal(0)
    )
    buckets = {**weights.allocation_by_asset_class, **weights.allocation_by_currency}

    return [
        StressScenario(
            name=scenario["name"],
            shock=scenario["shock"],
            portfolio_impact=sum(
                (
                    total_value * bucket_weight * scenario["shock"][bucket]
                    for bucket, bucket_weight in buckets.items()
                    if bucket in scenario["shock"]
                ),
                Decimal(0),
            ),
        )
        for scenario in scenarios
    ]


async def run_stress_brief(
    portfolio: Portfolio,
    fx_client: NbpFxClient,
    scenarios: list[dict] = DEFAULT_SCENARIOS,
) -> Brief:
    """P5-S3: the "Kwant" subagent — the one perspective with zero LLM
    calls (03-design.md's `subagents/stress.py` heading). FX conversion is
    the only I/O here; the scenario math itself is `compute_stress_scenarios`,
    a pure function the model never touches."""
    positions_with_base_value = [
        (position, await convert_to_base_currency(
            position.market_value, position.market_currency, portfolio.valuation_date, fx_client
        ))
        if position.market_value is not None and position.market_currency is not None
        else (position, Decimal(0))
        for position in portfolio.positions
    ]
    weights = compute_weights(positions_with_base_value)
    stress_scenarios = compute_stress_scenarios(weights, scenarios)

    claims = [
        Claim(
            text=f"{scenario.name}: wpływ na portfel {scenario.portfolio_impact:.2f} PLN.",
            source_type="computed_metric",
            source_ref="compute_stress_scenarios",
        )
        for scenario in stress_scenarios
    ]
    return Brief(
        perspective="stress",
        conclusion=" ".join(claim.text for claim in claims),
        confidence=1.0,  # certainty in the arithmetic, not in the scenario's real-world odds
        claims=claims,
    )
