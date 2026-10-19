from decimal import Decimal
from pathlib import Path

from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.market_pulse.brief import build_brief
from fin_ai_lab.market_pulse.models import IndicatorObservation, NewsItem, RegimeResult

PROMPTS_DIR = Path("src/fin_ai_lab/market_pulse/prompts")


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


def _us_indicator() -> IndicatorObservation:
    return IndicatorObservation(
        series_id="DGS10", label="Rentowność 10Y", value=Decimal("4.5"),
        unit="%", as_of_date="2026-09-17", source="fred",
    )


def _pl_indicator() -> IndicatorObservation:
    return IndicatorObservation(
        series_id="EUR/PLN", label="EUR/PLN", value=Decimal("4.3"),
        unit="PLN", as_of_date="2026-09-17", source="nbp-fx",
    )


def _news_item() -> NewsItem:
    return NewsItem(
        title="Spółka X ogłasza wyniki", summary="Zysk wzrósł o 10%.",
        source="bankier", link="https://example.com/x",
    )


async def test_build_brief_dispatches_one_worker_call_per_domain_and_assembles_text() -> None:
    llm_client = FakeLlmClient(
        {
            "brief_us": "Rentowność 10-letnich obligacji USA to 4.5%.",
            "brief_pl": "Kurs EUR/PLN wynosi 4.3.",
            "brief_news": "Spółka X podała wyniki, zysk wzrósł o 10%.",
        }
    )
    regime = RegimeResult(regime="neutral", signals=["Brak sygnałów przekraczających próg"])

    brief = await build_brief(
        [_us_indicator(), _pl_indicator()],
        regime,
        ["fred:UNRATE"],
        [_news_item()],
        llm_client,
        _prompt_registry(),
        "gemini-3.6-flash",
    )

    assert len(llm_client.requests) == 3
    assert {request.prompt_id for request in llm_client.requests} == {
        "brief_us", "brief_pl", "brief_news",
    }
    assert "Reżim rynku: neutral" in brief.text
    assert "Rentowność 10-letnich obligacji USA to 4.5%." in brief.text
    assert "Kurs EUR/PLN wynosi 4.3." in brief.text
    assert "Spółka X podała wyniki, zysk wzrósł o 10%." in brief.text
    assert "fred:UNRATE" in brief.text
    assert brief.regime == "neutral"
    assert brief.regime_rationale == regime.signals
    assert brief.indicators == [_us_indicator(), _pl_indicator()]
    assert brief.missing_sources == ["fred:UNRATE"]


async def test_build_brief_skips_a_worker_call_when_its_domain_has_no_data() -> None:
    llm_client = FakeLlmClient({"brief_pl": "Kurs EUR/PLN wynosi 4.3."})
    regime = RegimeResult(regime="neutral", signals=[])

    brief = await build_brief(
        [_pl_indicator()], regime, [], [], llm_client, _prompt_registry(), "gemini-3.6-flash"
    )

    assert len(llm_client.requests) == 1
    assert llm_client.requests[0].prompt_id == "brief_pl"
    assert "Brak danych o wskaźnikach USA" in brief.text
    assert "Brak newsów w tym przebiegu" in brief.text
