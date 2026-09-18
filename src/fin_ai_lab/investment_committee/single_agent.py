from datetime import date
from decimal import Decimal

from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.investment_committee.budget import BudgetGuard
from fin_ai_lab.investment_committee.models import CommitteeReport
from fin_ai_lab.investment_committee.tools import build_tools
from fin_ai_lab.market_pulse.sources.fred import FredClient
from fin_ai_lab.market_pulse.sources.nbp import NbpClient
from fin_ai_lab.portfolio_xray.canonical import Portfolio


async def run_single_agent(
    portfolio: Portfolio,
    portfolio_id: str,
    fred_client: FredClient,
    nbp_client: NbpClient,
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    budget: BudgetGuard,
) -> CommitteeReport:
    """P5-S1: one agent, all tools, automatic function calling — the same
    pattern P3-S2 established. This is the baseline P5-S7 compares the
    full committee against, not throwaway scaffolding (03-design.md)."""
    if not budget.check(Decimal(0)):
        return CommitteeReport(
            portfolio_id=portfolio_id,
            date=date.today(),
            text="Budżet wyczerpany przed startem przebiegu.",
        )

    tools = build_tools(portfolio, fred_client, nbp_client)
    prompt = prompt_registry.get("single_agent", 1)
    rendered = prompt.render(portfolio_id=portfolio_id)

    request = LlmRequest(
        model=model,
        messages=[{"role": "user", "text": rendered}],
        tools=tools,
        prompt_id="single_agent",
        prompt_version=1,
    )
    result = await llm_client.complete(request)
    budget.record(result.cost_usd)

    return CommitteeReport(
        portfolio_id=portfolio_id,
        date=date.today(),
        text=result.text,
        cost_usd=result.cost_usd,
    )
