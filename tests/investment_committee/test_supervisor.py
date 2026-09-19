from datetime import date
from decimal import Decimal
from pathlib import Path

from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.investment_committee.budget import BudgetGuard
from fin_ai_lab.investment_committee.supervisor import run_committee
from fin_ai_lab.portfolio_xray.canonical import Portfolio, Position

PROMPTS_DIR = Path("src/fin_ai_lab/investment_committee/prompts")

_ALL_SOURCED_CRITIC_VERDICT = (
    '{"claim_verdicts": [{"has_identifiable_source": true, "reason": "ok"}]}'
)


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


def _brief_json(perspective: str, conclusion: str, confidence: float, sourced: bool = True) -> str:
    claims = (
        f'[{{"text": "{conclusion}", "source_type": "tool_result", '
        f'"source_ref": "{perspective}_tool"}}]'
        if sourced and confidence > 0
        else "[]"
    )
    return (
        f'{{"perspective": "{perspective}", "conclusion": "{conclusion}", '
        f'"confidence": {confidence}, "claims": {claims}}}'
    )


async def test_run_committee_dispatches_four_subagents_critiques_and_assembles_report() -> None:
    llm_client = FakeLlmClient(
        {
            "fundamental": _brief_json("fundamental", "Dane niedostępne.", 0.0),
            "macro": _brief_json("macro", "Reżim neutralny.", 0.6),
            "sentiment": _brief_json("sentiment", "Dane niedostępne.", 0.0),
            "critic": _ALL_SOURCED_CRITIC_VERDICT,
        }
    )
    budget = BudgetGuard(budget_usd=Decimal("1.00"), max_iterations=10)

    report = await run_committee(
        _portfolio(), "portfolio-1", _FakeFredClient(), _FakeNbpClient(),
        llm_client, _prompt_registry(), "gemini-3.6-flash", budget,
        fx_client=_FakeFxClient(),
    )

    assert report.portfolio_id == "portfolio-1"
    assert {brief.perspective for brief in report.briefs} == {
        "fundamental", "macro", "sentiment", "stress",
    }
    assert "[macro]" in report.text
    assert "[stress]" in report.text
    assert "nie stanowi rekomendacji inwestycyjnej" in report.text
    # macro (confidence 0.6) and stress (confidence 1.0, always) go through
    # the critic (REQ-041); fundamental/sentiment stubs (confidence 0) don't.
    assert len(llm_client.requests) == 3 + 2


async def test_run_committee_flags_explicit_disagreement_between_perspectives() -> None:
    llm_client = FakeLlmClient(
        {
            "fundamental": _brief_json("fundamental", "Wzrost przychodów spółek w portfelu.", 0.8),
            "macro": _brief_json("macro", "Wysokie ryzyko spowolnienia gospodarczego.", 0.7),
            "sentiment": _brief_json("sentiment", "Dane niedostępne.", 0.0),
            "critic": _ALL_SOURCED_CRITIC_VERDICT,
        }
    )
    budget = BudgetGuard(budget_usd=Decimal("1.00"), max_iterations=10)

    report = await run_committee(
        _portfolio(), "portfolio-1", _FakeFredClient(), _FakeNbpClient(),
        llm_client, _prompt_registry(), "gemini-3.6-flash", budget,
        fx_client=_FakeFxClient(),
    )

    assert len(report.disagreements) == 1
    assert "fundamental" in report.disagreements[0]
    assert "macro" in report.disagreements[0]
    assert "Rozbieżności między perspektywami" in report.text


async def test_run_committee_drops_a_brief_the_critic_finds_unsourced() -> None:
    llm_client = FakeLlmClient(
        {
            "fundamental": _brief_json("fundamental", "Dane niedostępne.", 0.0),
            "macro": _brief_json("macro", "Reżim neutralny.", 0.6, sourced=False),
            "sentiment": _brief_json("sentiment", "Dane niedostępne.", 0.0),
            "critic": _ALL_SOURCED_CRITIC_VERDICT,
        }
    )
    budget = BudgetGuard(budget_usd=Decimal("1.00"), max_iterations=10)

    report = await run_committee(
        _portfolio(), "portfolio-1", _FakeFredClient(), _FakeNbpClient(),
        llm_client, _prompt_registry(), "gemini-3.6-flash", budget,
        fx_client=_FakeFxClient(),
    )

    macro_brief = next(brief for brief in report.briefs if brief.perspective == "macro")
    assert macro_brief.confidence == 0.0
    assert "ODRZUCONE PRZEZ KRYTYKA" in macro_brief.conclusion


async def test_run_committee_stops_before_dispatch_when_budget_exhausted() -> None:
    llm_client = FakeLlmClient({"fundamental": "x", "macro": "x", "sentiment": "x"})
    budget = BudgetGuard(budget_usd=Decimal("0"), max_iterations=10)
    budget.record(Decimal("0.01"))

    report = await run_committee(
        _portfolio(), "portfolio-1", _FakeFredClient(), _FakeNbpClient(),
        llm_client, _prompt_registry(), "gemini-3.6-flash", budget,
    )

    assert llm_client.requests == []
    assert "Budżet wyczerpany" in report.text
