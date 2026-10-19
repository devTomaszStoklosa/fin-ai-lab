from decimal import Decimal
from pathlib import Path

from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.investment_committee.budget import BudgetGuard
from fin_ai_lab.investment_committee.subagents.fundamental import run_fundamental_brief

PROMPTS_DIR = Path("src/fin_ai_lab/investment_committee/prompts")


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


async def _stub_tool(question: str) -> str:
    return f"Narzędzie P2 nie jest jeszcze podłączone — pytanie '{question}' bez odpowiedzi."


async def test_run_fundamental_brief_returns_parsed_brief_and_records_cost() -> None:
    response = (
        '{"perspective": "fundamental", "conclusion": "Dane niedostępne.", '
        '"confidence": 0.0, "claims": []}'
    )
    llm_client = FakeLlmClient({"fundamental": response})
    budget = BudgetGuard(budget_usd=Decimal("1.00"), max_iterations=10)

    brief = await run_fundamental_brief(
        _stub_tool, llm_client, _prompt_registry(), "gemini-3.6-flash", "portfolio-1", budget
    )

    assert brief.perspective == "fundamental"
    assert brief.confidence == 0.0
    assert len(llm_client.requests) == 1
    assert budget.iterations == 1


async def test_run_fundamental_brief_returns_stub_when_budget_exhausted() -> None:
    llm_client = FakeLlmClient({"fundamental": "should not be used"})
    budget = BudgetGuard(budget_usd=Decimal("0"), max_iterations=10)
    budget.record(Decimal("0.01"))

    brief = await run_fundamental_brief(
        _stub_tool, llm_client, _prompt_registry(), "gemini-3.6-flash", "portfolio-1", budget
    )

    assert llm_client.requests == []
    assert brief.confidence == 0.0
    assert "Budżet" in brief.conclusion
