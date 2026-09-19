import asyncio
import itertools
from datetime import date
from decimal import Decimal

from fin_ai_lab.core.llm.client import LlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.investment_committee.budget import BudgetGuard
from fin_ai_lab.investment_committee.models import Brief, CommitteeReport
from fin_ai_lab.investment_committee.subagents.fundamental import run_fundamental_brief
from fin_ai_lab.investment_committee.subagents.macro import run_macro_brief
from fin_ai_lab.investment_committee.subagents.sentiment import run_sentiment_brief
from fin_ai_lab.investment_committee.subagents.stress import run_stress_brief
from fin_ai_lab.investment_committee.tools import build_tools
from fin_ai_lab.market_pulse.sources.fred import FredClient
from fin_ai_lab.market_pulse.sources.nbp import NbpClient
from fin_ai_lab.portfolio_xray.canonical import Portfolio
from fin_ai_lab.portfolio_xray.metrics.fx import NbpFxClient

_NO_ADVICE_NOTICE = (
    "Powyższe zestawienie ma charakter wyłącznie informacyjny i nie stanowi rekomendacji "
    "inwestycyjnej ani porady dotyczącej kupna, sprzedaży czy przetrzymywania jakichkolwiek "
    "instrumentów finansowych."
)

# ASSUMPTION: REQ-002 only requires disagreement to be surfaced, not that
# detecting it is itself an LLM judgment call — 03-design.md's supervisor
# has no synthesis prompt of its own (only fundamental/macro/sentiment do),
# so this is a small, deterministic Polish keyword lexicon in code, not an
# NLP model. It only compares briefs that actually carry a signal
# (confidence > 0) — a stub brief (P2/P4 not wired) has nothing to disagree
# about.
_POSITIVE_WORDS = ("wzrost", "wzrosł", "wzrosn", "poprawa", "stabiln", "korzystn", "pozytywn")
_NEGATIVE_WORDS = ("spadek", "spadł", "spadn", "pogorszenie", "negatywn", "ryzyk", "zagrożeni")


async def run_committee(
    portfolio: Portfolio,
    portfolio_id: str,
    fred_client: FredClient,
    nbp_client: NbpClient,
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    budget: BudgetGuard,
    fx_client: NbpFxClient | None = None,
) -> CommitteeReport:
    """P5-S2/S3: orchestrator-workers, same pattern as P3-S4's `build_brief`
    — dispatches the four perspective subagents in parallel, then assembles
    the report in code (REQ-004: the supervisor never recomputes a number a
    subagent already produced, it only concatenates their conclusions and
    flags disagreement). The stress ("Kwant") subagent makes no LLM call at
    all (REQ-030) — its budget cost is always zero."""
    if not budget.check(Decimal(0)):
        return CommitteeReport(
            portfolio_id=portfolio_id,
            date=date.today(),
            text="Budżet wyczerpany przed startem przebiegu.",
        )

    tools_by_name = {
        tool.__name__: tool for tool in build_tools(portfolio, fred_client, nbp_client)
    }

    briefs = list(
        await asyncio.gather(
            run_fundamental_brief(
                tools_by_name["ask_about_filings"],
                llm_client, prompt_registry, model, portfolio_id, budget,
            ),
            run_macro_brief(
                tools_by_name["get_market_regime"],
                llm_client, prompt_registry, model, portfolio_id, budget,
            ),
            run_sentiment_brief(
                tools_by_name["get_news_sentiment"],
                llm_client, prompt_registry, model, portfolio_id, budget,
            ),
            run_stress_brief(portfolio, fx_client or NbpFxClient()),
        )
    )

    disagreements = _detect_disagreements(briefs)
    return CommitteeReport(
        portfolio_id=portfolio_id,
        date=date.today(),
        briefs=briefs,
        disagreements=disagreements,
        text=_assemble_text(briefs, disagreements),
        cost_usd=budget.spent_usd,
    )


def _detect_disagreements(briefs: list[Brief]) -> list[str]:
    signal_briefs = [brief for brief in briefs if brief.confidence > 0]
    disagreements = []
    for first, second in itertools.combinations(signal_briefs, 2):
        stance_first, stance_second = _stance(first.conclusion), _stance(second.conclusion)
        if "neutral" in (stance_first, stance_second) or stance_first == stance_second:
            continue
        disagreements.append(
            f"{first.perspective} ({stance_first}, pewność {first.confidence:.2f}) "
            f"vs {second.perspective} ({stance_second}, pewność {second.confidence:.2f})"
        )
    return disagreements


def _stance(conclusion: str) -> str:
    lowered = conclusion.lower()
    is_positive = any(word in lowered for word in _POSITIVE_WORDS)
    is_negative = any(word in lowered for word in _NEGATIVE_WORDS)
    if is_positive and not is_negative:
        return "positive"
    if is_negative and not is_positive:
        return "negative"
    return "neutral"


def _assemble_text(briefs: list[Brief], disagreements: list[str]) -> str:
    sections = [
        f"[{brief.perspective}] {brief.conclusion} (pewność: {brief.confidence:.2f})"
        for brief in briefs
    ]
    if disagreements:
        sections.append("Rozbieżności między perspektywami: " + "; ".join(disagreements))
    sections.append(_NO_ADVICE_NOTICE)
    return "\n\n".join(sections)
