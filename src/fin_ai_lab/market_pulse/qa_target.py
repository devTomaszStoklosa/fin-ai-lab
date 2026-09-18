from decimal import Decimal

from fin_ai_lab.core.config import Settings
from fin_ai_lab.core.evals.models import RunContext
from fin_ai_lab.market_pulse.agent import ask
from fin_ai_lab.market_pulse.models import IndicatorObservation
from fin_ai_lab.market_pulse.regime import classify_regime
from fin_ai_lab.market_pulse.sources.fred import FredClient
from fin_ai_lab.market_pulse.sources.nbp import NbpClient


async def trajectory_target(case_input: dict, ctx: RunContext) -> dict:
    """p3-trajectory (docs/EVALS.md): did the agent call the right
    tool(s) to answer, not just produce plausible-sounding text."""
    model = ctx.model or "gemini-3.6-flash"
    settings = Settings()
    fred_client = FredClient(settings.require_fred_api_key())
    nbp_client = NbpClient()

    answer = await ask(
        case_input["question"], ctx.llm_client, ctx.prompts, model, fred_client, nbp_client
    )
    return {
        "text": answer.text,
        "tool_calls": answer.tool_calls,
        "step_count": len(answer.tool_calls),
    }


async def regime_backtest_target(case_input: dict, _ctx: RunContext) -> dict:
    """p3-regime-backtest (docs/EVALS.md): classify_regime is pure,
    deterministic code (REQ-010) — no LLM call, so no "model knows the
    future from training data" risk (02-spec.md backtest concern) and no
    date anonymization needed. This target only exercises the rule's
    thresholds (regime.py, marked ASSUMPTION) against real historical
    indicator values given directly in the case, not fetched live — a
    backtest must stay deterministic and reproducible, not depend on
    whatever a live API returns today."""
    indicators = [
        IndicatorObservation(
            series_id=item["series_id"],
            label=item["series_id"],
            value=Decimal(str(item["value"])),
            unit=item.get("unit", ""),
            as_of_date=case_input["as_of_date"],
            source=item.get("source", "fred"),
        )
        for item in case_input["indicators"]
    ]
    result = classify_regime(indicators)
    return {"regime": result.regime, "signals": result.signals}
