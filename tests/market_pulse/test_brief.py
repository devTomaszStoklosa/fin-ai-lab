from decimal import Decimal
from pathlib import Path

from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.market_pulse.brief import build_brief
from fin_ai_lab.market_pulse.models import IndicatorObservation, RegimeResult

PROMPTS_DIR = Path("src/fin_ai_lab/market_pulse/prompts")


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


async def test_build_brief_returns_the_llm_text_with_computed_fields_untouched() -> None:
    llm_client = FakeLlmClient({"brief": "Reżim neutralny, brak istotnych zmian."})
    indicators = [
        IndicatorObservation(
            series_id="DGS10", label="Rentowność 10Y", value=Decimal("4.5"),
            unit="%", as_of_date="2026-09-17", source="fred",
        )
    ]
    regime = RegimeResult(regime="neutral", signals=["Brak sygnałów przekraczających próg"])

    brief = await build_brief(
        indicators, regime, ["fred:UNRATE"], llm_client, _prompt_registry(), "gemini-3.6-flash"
    )

    assert brief.text == "Reżim neutralny, brak istotnych zmian."
    assert brief.regime == "neutral"
    assert brief.regime_rationale == regime.signals
    assert brief.indicators == indicators
    assert brief.missing_sources == ["fred:UNRATE"]
