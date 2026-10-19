from decimal import Decimal
from pathlib import Path

from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.investment_committee.budget import BudgetGuard
from fin_ai_lab.investment_committee.subagents.macro import run_macro_brief

PROMPTS_DIR = Path("src/fin_ai_lab/investment_committee/prompts")


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


async def _stub_tool() -> str:
    return "Reżim rynku: neutral. Sygnały: brak sygnałów progowych."


async def test_run_macro_brief_returns_parsed_brief_and_records_cost() -> None:
    response = (
        '{"perspective": "macro", "conclusion": "Reżim neutralny, brak sygnałów progowych.", '
        '"confidence": 0.7, "claims": []}'
    )
    llm_client = FakeLlmClient({"macro": response})
    budget = BudgetGuard(budget_usd=Decimal("1.00"), max_iterations=10)

    brief = await run_macro_brief(
        _stub_tool, llm_client, _prompt_registry(), "gemini-3.6-flash", "portfolio-1", budget
    )

    assert brief.perspective == "macro"
    assert brief.confidence == 0.7
    assert budget.iterations == 1


async def test_run_macro_brief_returns_stub_when_budget_exhausted() -> None:
    llm_client = FakeLlmClient({"macro": "should not be used"})
    budget = BudgetGuard(budget_usd=Decimal("0"), max_iterations=10)
    budget.record(Decimal("0.01"))

    brief = await run_macro_brief(
        _stub_tool, llm_client, _prompt_registry(), "gemini-3.6-flash", "portfolio-1", budget
    )

    assert llm_client.requests == []
    assert brief.confidence == 0.0
