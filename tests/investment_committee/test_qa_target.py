from datetime import date
from decimal import Decimal
from pathlib import Path

from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.investment_committee.qa_target import compare_committee_vs_single
from fin_ai_lab.portfolio_xray.canonical import Portfolio, Position

PROMPTS_DIR = Path("src/fin_ai_lab/investment_committee/prompts")

_CRITIC_PASS = '{"claim_verdicts": [{"has_identifiable_source": true, "reason": "ok"}]}'


class _FakeFredClient:
    async def latest_observation(self, series_id: str, **kwargs):
        return None


class _FakeNbpClient:
    async def fetch_fx_rate(self, code: str, **kwargs):
        return None


class _FakeFxClient:
    async def mid_rate(self, currency: str, as_of):
        return Decimal(1)


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


def _portfolio() -> Portfolio:
    return Portfolio(
        valuation_date=date(2026, 9, 17),
        positions=[
            Position(
                broker="xtb", account_type="regular", instrument_name="Orlen",
                asset_class="equity", quantity=Decimal("10"),
                market_value=Decimal("1000"), market_currency="PLN",
                valuation_date=date(2026, 9, 17),
            )
        ],
    )


def _brief_json(perspective: str, conclusion: str, confidence: float) -> str:
    claims = (
        f'[{{"text": "{conclusion}", "source_type": "tool_result", '
        f'"source_ref": "{perspective}_tool"}}]'
        if confidence > 0
        else "[]"
    )
    return (
        f'{{"perspective": "{perspective}", "conclusion": "{conclusion}", '
        f'"confidence": {confidence}, "claims": {claims}}}'
    )


async def test_compare_committee_vs_single_runs_both_variants_and_judges_quality() -> None:
    llm_client = FakeLlmClient(
        {
            "single_agent": "Analiza jednoagentowa.",
            "fundamental": _brief_json("fundamental", "Dane niedostępne.", 0.0),
            "macro": _brief_json("macro", "Reżim neutralny.", 0.6),
            "sentiment": _brief_json("sentiment", "Dane niedostępne.", 0.0),
            "critic": _CRITIC_PASS,
            "comparison_judge": '{"winner": "b", "reason": "Komitet pokrywa więcej perspektyw."}',
        }
    )

    report = await compare_committee_vs_single(
        _portfolio(), "portfolio-1", _FakeFredClient(), _FakeNbpClient(),
        llm_client, _prompt_registry(), "gemini-3.6-flash", Decimal("1.00"),
        fx_client=_FakeFxClient(),
    )

    assert report.portfolio_id == "portfolio-1"
    assert report.single_agent.text == "Analiza jednoagentowa."
    assert report.quality_winner == "committee"
    assert "Komitet" in report.quality_reason
    assert report.single_agent.latency_ms >= 0
    assert report.committee.latency_ms >= 0


async def test_compare_committee_vs_single_defaults_unknown_verdict_letter_to_tie() -> None:
    llm_client = FakeLlmClient(
        {
            "single_agent": "Analiza jednoagentowa.",
            "fundamental": _brief_json("fundamental", "Dane niedostępne.", 0.0),
            "macro": _brief_json("macro", "Reżim neutralny.", 0.6),
            "sentiment": _brief_json("sentiment", "Dane niedostępne.", 0.0),
            "critic": _CRITIC_PASS,
            "comparison_judge": '{"winner": "tie", "reason": "Porównywalna jakość."}',
        }
    )

    report = await compare_committee_vs_single(
        _portfolio(), "portfolio-1", _FakeFredClient(), _FakeNbpClient(),
        llm_client, _prompt_registry(), "gemini-3.6-flash", Decimal("1.00"),
        fx_client=_FakeFxClient(),
    )

    assert report.quality_winner == "tie"
