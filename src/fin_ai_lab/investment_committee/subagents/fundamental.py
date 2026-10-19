from collections.abc import Awaitable, Callable
from decimal import Decimal

from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.investment_committee.budget import BudgetGuard
from fin_ai_lab.investment_committee.models import Brief

# ASSUMPTION: 03-design.md doesn't fix what question a non-AFC fundamental
# subagent should ask P2's filings tool (S1's single agent picks its own via
# AFC; this subagent doesn't). Fixed and deterministic, not model-chosen,
# until P2's real retrieval is wired here.
DEFAULT_QUESTION = "Czy sprawozdania finansowe posiadanych spółek wskazują na istotne ryzyka?"

_BUDGET_EXHAUSTED_BRIEF = Brief(
    perspective="fundamental",
    conclusion="Budżet komitetu wyczerpany przed wywołaniem perspektywy fundamentalnej.",
    confidence=0.0,
)


async def run_fundamental_brief(
    ask_about_filings: Callable[[str], Awaitable[str]],
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    portfolio_id: str,
    budget: BudgetGuard,
) -> Brief:
    """P5-S2: fundamental subagent. Unlike S1's single_agent (AFC — the
    model picks its own tools), this is a fixed one-tool-per-perspective
    pipeline (03-design.md rollout #2): call P2's tool once, then one LLM
    call with response_schema=Brief over its result."""
    if not budget.check(Decimal(0)):
        return _BUDGET_EXHAUSTED_BRIEF

    tool_result = await ask_about_filings(DEFAULT_QUESTION)
    prompt = prompt_registry.get("fundamental", 1)
    request = LlmRequest(
        model=model,
        messages=[
            {
                "role": "user",
                "text": prompt.render(portfolio_id=portfolio_id, tool_result=tool_result),
            }
        ],
        response_schema=Brief,
        prompt_id="fundamental",
        prompt_version=1,
    )
    result = await llm_client.complete(request)
    budget.record(result.cost_usd)

    brief = result.parsed
    if not isinstance(brief, Brief):
        raise ValueError("fundamental subagent response did not match Brief schema")
    return brief
