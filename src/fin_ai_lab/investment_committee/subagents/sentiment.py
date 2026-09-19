from collections.abc import Awaitable, Callable
from decimal import Decimal

from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.investment_committee.budget import BudgetGuard
from fin_ai_lab.investment_committee.models import Brief

# ASSUMPTION: same reasoning as fundamental.py's DEFAULT_QUESTION — there's
# no per-holding headline feed wired into investment_committee yet, so this
# subagent asks P4's tool about the portfolio in aggregate. The stub ignores
# the argument's content anyway (03-design.md risk: P4 not ready as S2 is
# built), so this doesn't need to be a real headline.
DEFAULT_HEADLINE = "Zbiorczy sentyment nagłówków dotyczących spółek z portfela"

_BUDGET_EXHAUSTED_BRIEF = Brief(
    perspective="sentiment",
    conclusion="Budżet komitetu wyczerpany przed wywołaniem perspektywy sentymentu.",
    confidence=0.0,
)


async def run_sentiment_brief(
    get_news_sentiment: Callable[[str], Awaitable[str]],
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    portfolio_id: str,
    budget: BudgetGuard,
) -> Brief:
    """P5-S2: sentiment subagent — same fixed one-tool pipeline as
    fundamental.py, wrapping P4's news-classifier tool instead of P2's."""
    if not budget.check(Decimal(0)):
        return _BUDGET_EXHAUSTED_BRIEF

    tool_result = await get_news_sentiment(DEFAULT_HEADLINE)
    prompt = prompt_registry.get("sentiment", 1)
    request = LlmRequest(
        model=model,
        messages=[
            {
                "role": "user",
                "text": prompt.render(portfolio_id=portfolio_id, tool_result=tool_result),
            }
        ],
        response_schema=Brief,
        prompt_id="sentiment",
        prompt_version=1,
    )
    result = await llm_client.complete(request)
    budget.record(result.cost_usd)

    brief = result.parsed
    if not isinstance(brief, Brief):
        raise ValueError("sentiment subagent response did not match Brief schema")
    return brief
