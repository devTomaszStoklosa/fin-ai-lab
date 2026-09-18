from datetime import date
from decimal import Decimal
from pathlib import Path

from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.investment_committee.budget import BudgetGuard
from fin_ai_lab.investment_committee.single_agent import run_single_agent
from fin_ai_lab.market_pulse.sources.fred import FredClient
from fin_ai_lab.market_pulse.sources.nbp import NbpClient
from fin_ai_lab.portfolio_xray.canonical import Portfolio, Position

PROMPTS_DIR = Path("src/fin_ai_lab/investment_committee/prompts")


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


async def test_run_single_agent_returns_the_llm_report_and_records_cost() -> None:
    llm_client = FakeLlmClient({"single_agent": "Analiza portfela: alokacja skoncentrowana."})
    budget = BudgetGuard(budget_usd=Decimal("1.00"), max_iterations=10)

    report = await run_single_agent(
        _portfolio(), "portfolio-1", FredClient("fake-key"), NbpClient(),
        llm_client, _prompt_registry(), "gemini-3.6-flash", budget,
    )

    assert report.text == "Analiza portfela: alokacja skoncentrowana."
    assert report.portfolio_id == "portfolio-1"
    assert len(llm_client.requests) == 1
    tool_names = {tool.__name__ for tool in llm_client.requests[0].tools}
    assert tool_names == {
        "get_portfolio_allocation", "get_market_regime", "ask_about_filings",
        "get_news_sentiment",
    }
    assert budget.iterations == 1


async def test_run_single_agent_stops_before_calling_the_llm_when_budget_exhausted() -> None:
    llm_client = FakeLlmClient({"single_agent": "should not be used"})
    budget = BudgetGuard(budget_usd=Decimal("0"), max_iterations=10)
    budget.record(Decimal("0.01"))  # already over the zero budget

    report = await run_single_agent(
        _portfolio(), "portfolio-1", FredClient("fake-key"), NbpClient(),
        llm_client, _prompt_registry(), "gemini-3.6-flash", budget,
    )

    assert llm_client.requests == []
    assert "Budżet wyczerpany" in report.text
