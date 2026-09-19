from collections.abc import Awaitable, Callable
from decimal import Decimal

from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.investment_committee.budget import BudgetGuard
from fin_ai_lab.investment_committee.models import Brief

_BUDGET_EXHAUSTED_BRIEF = Brief(
    perspective="macro",
    conclusion="Budżet komitetu wyczerpany przed wywołaniem perspektywy makro.",
    confidence=0.0,
)


async def run_macro_brief(
    get_market_regime: Callable[[], Awaitable[str]],
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    portfolio_id: str,
    budget: BudgetGuard,
) -> Brief:
    """P5-S2: macro subagent — same fixed one-tool pipeline as
    fundamental.py, wrapping P3's market-regime tool instead of P2's."""
    if not budget.check(Decimal(0)):
        return _BUDGET_EXHAUSTED_BRIEF

    tool_result = await get_market_regime()
    prompt = prompt_registry.get("macro", 1)
    request = LlmRequest(
        model=model,
        messages=[
            {
                "role": "user",
                "text": prompt.render(portfolio_id=portfolio_id, tool_result=tool_result),
            }
        ],
        response_schema=Brief,
        prompt_id="macro",
        prompt_version=1,
    )
    result = await llm_client.complete(request)
    budget.record(result.cost_usd)

    brief = result.parsed
    if not isinstance(brief, Brief):
        raise ValueError("macro subagent response did not match Brief schema")
    return brief
