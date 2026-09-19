import time
from decimal import Decimal

from pydantic import BaseModel

from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.investment_committee.budget import BudgetGuard
from fin_ai_lab.investment_committee.models import ComparisonReport, VariantResult
from fin_ai_lab.investment_committee.single_agent import run_single_agent
from fin_ai_lab.investment_committee.supervisor import run_committee
from fin_ai_lab.market_pulse.sources.fred import FredClient
from fin_ai_lab.market_pulse.sources.nbp import NbpClient
from fin_ai_lab.portfolio_xray.canonical import Portfolio
from fin_ai_lab.portfolio_xray.metrics.fx import NbpFxClient

DEFAULT_MAX_ITERATIONS = 10

_WINNER_BY_LETTER = {"a": "single_agent", "b": "committee", "tie": "tie"}


class _ComparisonVerdict(BaseModel):
    winner: str
    reason: str


async def compare_committee_vs_single(
    portfolio: Portfolio,
    portfolio_id: str,
    fred_client: FredClient,
    nbp_client: NbpClient,
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    budget_usd: Decimal,
    fx_client: NbpFxClient | None = None,
) -> ComparisonReport:
    """P5-S7, REQ-050: pairwise comparison on the same portfolio and the
    same per-variant budget (01-story.md's "ten sam budżet" — each variant
    gets its own BudgetGuard with an identical cap, not one shared guard,
    so neither can starve the other's spending). Quality is judged blind
    (the judge sees "report a"/"report b", never which variant produced
    which — 03-design.md has no synthesis prompt that would let either
    subagent or the supervisor grade its own work)."""
    single_result = await _timed_run(
        run_single_agent(
            portfolio, portfolio_id, fred_client, nbp_client, llm_client, prompt_registry, model,
            BudgetGuard(budget_usd=budget_usd, max_iterations=DEFAULT_MAX_ITERATIONS),
        )
    )
    committee_result = await _timed_run(
        run_committee(
            portfolio, portfolio_id, fred_client, nbp_client, llm_client, prompt_registry, model,
            BudgetGuard(budget_usd=budget_usd, max_iterations=DEFAULT_MAX_ITERATIONS),
            fx_client=fx_client,
        )
    )

    verdict = await _judge_quality(
        portfolio_id, single_result.text, committee_result.text, llm_client, prompt_registry, model
    )

    return ComparisonReport(
        portfolio_id=portfolio_id,
        single_agent=single_result,
        committee=committee_result,
        quality_winner=_WINNER_BY_LETTER.get(verdict.winner, "tie"),
        quality_reason=verdict.reason,
    )


async def _timed_run(coro) -> VariantResult:
    started = time.monotonic()
    report = await coro
    latency_ms = int((time.monotonic() - started) * 1000)
    return VariantResult(text=report.text, cost_usd=report.cost_usd, latency_ms=latency_ms)


async def _judge_quality(
    portfolio_id: str,
    single_agent_text: str,
    committee_text: str,
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
) -> _ComparisonVerdict:
    prompt = prompt_registry.get("comparison_judge", 1)
    request = LlmRequest(
        model=model,
        messages=[
            {
                "role": "user",
                "text": prompt.render(
                    portfolio_id=portfolio_id, report_a=single_agent_text, report_b=committee_text
                ),
            }
        ],
        response_schema=_ComparisonVerdict,
        prompt_id="comparison_judge",
        prompt_version=1,
    )
    result = await llm_client.complete(request)
    verdict = result.parsed
    if not isinstance(verdict, _ComparisonVerdict):
        raise ValueError(f"comparison judge for '{portfolio_id}' returned no parsed verdict")
    return verdict
