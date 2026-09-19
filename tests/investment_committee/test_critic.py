from decimal import Decimal
from pathlib import Path

from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.investment_committee.budget import BudgetGuard
from fin_ai_lab.investment_committee.critic import critique_brief
from fin_ai_lab.investment_committee.models import Brief, Claim

PROMPTS_DIR = Path("src/fin_ai_lab/investment_committee/prompts")


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


def _sourced_brief() -> Brief:
    return Brief(
        perspective="macro",
        conclusion="Reżim neutralny.",
        confidence=0.7,
        claims=[
            Claim(text="Reżim: neutral.", source_type="tool_result", source_ref="get_market_regime")
        ],
    )


async def test_critique_brief_skips_the_llm_when_confidence_is_zero() -> None:
    stub_brief = Brief(perspective="fundamental", conclusion="Dane niedostępne.", confidence=0.0)
    llm_client = FakeLlmClient({"critic": "should not be used"})
    budget = BudgetGuard(budget_usd=Decimal("1.00"), max_iterations=10)

    result = await critique_brief(
        stub_brief, llm_client, _prompt_registry(), "gemini-3.6-flash", budget
    )

    assert result == stub_brief
    assert llm_client.requests == []


async def test_critique_brief_rejects_a_brief_with_confidence_but_no_claims() -> None:
    unsourced_brief = Brief(
        perspective="macro", conclusion="Reżim risk-on.", confidence=0.8, claims=[]
    )
    llm_client = FakeLlmClient({"critic": "should not be used"})
    budget = BudgetGuard(budget_usd=Decimal("1.00"), max_iterations=10)

    result = await critique_brief(
        unsourced_brief, llm_client, _prompt_registry(), "gemini-3.6-flash", budget
    )

    assert result.confidence == 0.0
    assert "ODRZUCONE" in result.conclusion
    assert llm_client.requests == []


async def test_critique_brief_keeps_a_brief_whose_claims_all_pass() -> None:
    brief = _sourced_brief()
    llm_client = FakeLlmClient(
        {"critic": '{"claim_verdicts": [{"has_identifiable_source": true, "reason": "ok"}]}'}
    )
    budget = BudgetGuard(budget_usd=Decimal("1.00"), max_iterations=10)

    result = await critique_brief(brief, llm_client, _prompt_registry(), "gemini-3.6-flash", budget)

    assert result == brief
    assert budget.iterations == 1


async def test_critique_brief_strips_unsourced_claims_flagged_by_the_critic() -> None:
    brief = Brief(
        perspective="macro",
        conclusion="Reżim neutralny, poza tym rosnąca inflacja.",
        confidence=0.7,
        claims=[
            Claim(
                text="Reżim: neutral.", source_type="tool_result", source_ref="get_market_regime"
            ),
            Claim(text="Inflacja rośnie.", source_type="tool_result", source_ref="wiedza ogólna"),
        ],
    )
    llm_client = FakeLlmClient(
        {
            "critic": (
                '{"claim_verdicts": ['
                '{"has_identifiable_source": true, "reason": "ok"}, '
                '{"has_identifiable_source": false, "reason": "brak konkretnego źródła"}'
                ']}'
            )
        }
    )
    budget = BudgetGuard(budget_usd=Decimal("1.00"), max_iterations=10)

    result = await critique_brief(brief, llm_client, _prompt_registry(), "gemini-3.6-flash", budget)

    assert len(result.claims) == 1
    assert result.claims[0].source_ref == "get_market_regime"
    assert result.confidence == 0.7  # unchanged — brief still has at least one sourced claim


async def test_critique_brief_rejects_entirely_when_no_claim_passes() -> None:
    brief = Brief(
        perspective="macro",
        conclusion="Rosnąca inflacja.",
        confidence=0.7,
        claims=[
            Claim(text="Inflacja rośnie.", source_type="tool_result", source_ref="wiedza ogólna")
        ],
    )
    llm_client = FakeLlmClient(
        {
            "critic": (
                '{"claim_verdicts": [{"has_identifiable_source": false, "reason": "brak źródła"}]}'
            )
        }
    )
    budget = BudgetGuard(budget_usd=Decimal("1.00"), max_iterations=10)

    result = await critique_brief(brief, llm_client, _prompt_registry(), "gemini-3.6-flash", budget)

    assert result.confidence == 0.0
    assert result.claims == []
    assert "ODRZUCONE" in result.conclusion


async def test_critique_brief_rejects_when_budget_exhausted_instead_of_passing_unverified() -> None:
    brief = _sourced_brief()
    llm_client = FakeLlmClient({"critic": "should not be used"})
    budget = BudgetGuard(budget_usd=Decimal("0"), max_iterations=10)
    budget.record(Decimal("0.01"))

    result = await critique_brief(brief, llm_client, _prompt_registry(), "gemini-3.6-flash", budget)

    assert result.confidence == 0.0
    assert llm_client.requests == []
