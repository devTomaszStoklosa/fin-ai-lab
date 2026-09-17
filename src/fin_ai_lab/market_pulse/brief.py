import json
from datetime import date

from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.market_pulse.models import Brief, IndicatorObservation, RegimeResult


async def build_brief(
    indicators: list[IndicatorObservation],
    regime: RegimeResult,
    missing_sources: list[str],
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
) -> Brief:
    prompt = prompt_registry.get("brief", 1)
    rendered = prompt.render(
        regime=regime.regime,
        regime_signals="; ".join(regime.signals),
        indicators_json=json.dumps(_indicators_payload(indicators), ensure_ascii=False),
        missing_sources=", ".join(missing_sources) if missing_sources else "brak",
    )

    request = LlmRequest(
        model=model,
        messages=[{"role": "user", "text": rendered}],
        prompt_id="brief",
        prompt_version=1,
    )
    result = await llm_client.complete(request)

    return Brief(
        date=date.today(),
        regime=regime.regime,
        regime_rationale=regime.signals,
        indicators=indicators,
        missing_sources=missing_sources,
        text=result.text,
    )


def _indicators_payload(indicators: list[IndicatorObservation]) -> list[dict]:
    return [
        {
            "series_id": observation.series_id,
            "label": observation.label,
            "value": str(observation.value),
            "unit": observation.unit,
            "as_of_date": observation.as_of_date.isoformat(),
        }
        for observation in indicators
    ]
