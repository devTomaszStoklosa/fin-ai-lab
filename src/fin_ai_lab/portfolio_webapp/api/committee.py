"""Investment committee analysis: background jobs and the budget confirmation."""

import asyncio
import threading
from collections.abc import Callable
from decimal import Decimal
from typing import cast
from uuid import UUID

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.datastructures import State

from fin_ai_lab.core.llm.client import LlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.investment_committee.service import (
    BudgetGuard,
    CommitteeReport,
    ComparisonReport,
    compare_committee_vs_single,
    run_committee,
    run_single_agent,
)
from fin_ai_lab.market_pulse.service import FredClient, NbpClient
from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.api.common import (
    current_position_rows,
    current_reporting_context,
    get_db,
    position_row_to_domain,
)
from fin_ai_lab.portfolio_webapp.api.defaults import (
    CONFIRMATION_TIMEOUT_S,
    MODEL,
)
from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.schemas import (
    CommitteeAnalysisRequest,
    CommitteeJobOut,
    CommitteeJobStatus,
    CommitteeVariant,
    ConfirmBudgetRequest,
)
from fin_ai_lab.portfolio_xray.canonical import Portfolio
from fin_ai_lab.portfolio_xray.metrics.fx import NbpFxClient


def _to_committee_job_out(row: repository.CommitteeJobRow) -> CommitteeJobOut:
    (
        job_id,
        _portfolio_id,
        _snapshot_id,
        variant,
        status,
        created_at,
        finished_at,
        _model,
        cost_usd,
        error,
        result_json,
    ) = row
    result: CommitteeReport | ComparisonReport | None = None
    if result_json is not None:
        result = (
            ComparisonReport.model_validate_json(result_json)
            if variant == "compare"
            else CommitteeReport.model_validate_json(result_json)
        )
    return CommitteeJobOut(
        job_id=job_id,
        variant=cast(CommitteeVariant, variant),
        status=cast(CommitteeJobStatus, status),
        created_at=created_at,
        finished_at=finished_at,
        cost_usd=cost_usd,
        error=error,
        result=result,
    )


def _committee_result_cost(result: CommitteeReport | ComparisonReport) -> Decimal:
    if isinstance(result, ComparisonReport):
        return result.single_agent.cost_usd + result.committee.cost_usd
    return result.cost_usd


def _make_confirm_callback(state: State, job_id: UUID) -> Callable[[], bool]:
    # Runs INSIDE the worker thread started by asyncio.to_thread below
    # (BudgetGuard.on_budget_exceeded is called synchronously, deep in
    # run_committee/run_single_agent's call graph) -- blocking here
    # blocks only that thread, never the main event loop, so the server
    # stays responsive to GET/confirm requests while a job waits.
    def on_budget_exceeded() -> bool:
        repository.update_committee_job_status(state.db.cursor(), job_id, "awaiting_confirmation")
        event = threading.Event()
        state.committee_confirmations[job_id] = event
        answered = event.wait(timeout=CONFIRMATION_TIMEOUT_S)
        decision = state.committee_confirmation_decisions.pop(job_id, False)
        if not answered:
            decision = False
        state.committee_confirmations.pop(job_id, None)
        repository.update_committee_job_status(state.db.cursor(), job_id, "running")
        return decision

    return on_budget_exceeded


def _run_variant_sync(
    variant: str,
    portfolio: Portfolio,
    portfolio_id: str,
    fred_client: FredClient,
    nbp_client: NbpClient,
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    fx_client: NbpFxClient,
    budget: BudgetGuard | None,
    committee_budget_usd: Decimal,
) -> CommitteeReport | ComparisonReport:
    # A fresh event loop for this worker thread (asyncio.to_thread hands
    # us a plain OS thread with none running) -- safe and standard for
    # bridging blocking code into an async server.
    if variant == "single":
        assert budget is not None
        return asyncio.run(
            run_single_agent(
                portfolio,
                portfolio_id,
                fred_client,
                nbp_client,
                llm_client,
                prompt_registry,
                MODEL,
                budget,
            )
        )
    if variant == "committee":
        assert budget is not None
        return asyncio.run(
            run_committee(
                portfolio,
                portfolio_id,
                fred_client,
                nbp_client,
                llm_client,
                prompt_registry,
                MODEL,
                budget,
                fx_client=fx_client,
            )
        )
    # "compare": qa_target.compare_committee_vs_single builds its own,
    # non-overridable BudgetGuard per variant (no confirm-flow support --
    # matches the CLI's own `investment-committee compare`, which has no
    # --yes-style budget-override flag either).
    return asyncio.run(
        compare_committee_vs_single(
            portfolio,
            portfolio_id,
            fred_client,
            nbp_client,
            llm_client,
            prompt_registry,
            MODEL,
            committee_budget_usd,
            fx_client=fx_client,
        )
    )


async def _run_committee_job(
    state: State, deps: AppDeps, job_id: UUID, portfolio: Portfolio, portfolio_id: str, variant: str
) -> None:
    repository.update_committee_job_status(state.db.cursor(), job_id, "running")

    llm_client = deps.llm_client_factory()
    fred_client = deps.fred_client_factory()
    nbp_client = deps.nbp_client_factory()
    fx_client = deps.fx_client_factory()
    prompt_registry = state.prompt_registry

    budget = None
    if variant in ("single", "committee"):
        budget = BudgetGuard(
            budget_usd=deps.committee_budget_usd,
            max_iterations=deps.committee_max_iterations,
            on_budget_exceeded=_make_confirm_callback(state, job_id),
        )

    try:
        result = await asyncio.to_thread(
            _run_variant_sync,
            variant,
            portfolio,
            portfolio_id,
            fred_client,
            nbp_client,
            llm_client,
            prompt_registry,
            fx_client,
            budget,
            deps.committee_budget_usd,
        )
    except Exception as exc:
        # A job's failure must never crash this background task silently
        # -- it has to land in the job row, or the frontend would poll a
        # job stuck in "running" forever.
        repository.finish_committee_job(state.db.cursor(), job_id, status="failed", error=str(exc))
        return

    repository.finish_committee_job(
        state.db.cursor(),
        job_id,
        status="done",
        cost_usd=_committee_result_cost(result),
        result_json=result.model_dump_json(),
    )


def build_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/portfolios/{portfolio_id}/committee-analysis",
        response_model=CommitteeJobOut,
    )
    async def start_committee_analysis(
        portfolio_id: UUID,
        payload: CommitteeAnalysisRequest,
        request: Request,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> CommitteeJobOut:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        context = current_reporting_context(connection, portfolio_id)
        if context is None:
            raise HTTPException(status_code=422, detail="Portfolio has no positions yet")
        snapshot_id, valuation_date = context

        if not payload.regenerate:
            cached = repository.find_latest_done_committee_job(
                connection, snapshot_id, payload.variant
            )
            if cached is not None:
                return _to_committee_job_out(cached)

        rows = current_position_rows(connection, portfolio_id)
        positions = [position_row_to_domain(row) for row in rows]
        portfolio = Portfolio(positions=positions, valuation_date=valuation_date)

        job_row = repository.create_committee_job(
            connection,
            portfolio_id=portfolio_id,
            snapshot_id=snapshot_id,
            variant=payload.variant,
            model=MODEL,
        )
        job_id = job_row[0]

        task = asyncio.create_task(
            _run_committee_job(
                request.app.state, deps, job_id, portfolio, str(portfolio_id), payload.variant
            )
        )
        request.app.state.committee_job_tasks.add(task)
        task.add_done_callback(request.app.state.committee_job_tasks.discard)

        return _to_committee_job_out(job_row)

    @router.get(
        "/api/portfolios/{portfolio_id}/committee-analysis/{job_id}",
        response_model=CommitteeJobOut,
    )
    def get_committee_analysis_job(
        portfolio_id: UUID,
        job_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> CommitteeJobOut:
        job_row = repository.get_committee_job(connection, job_id)
        if job_row is None or job_row[1] != portfolio_id:
            raise HTTPException(status_code=404, detail="Job not found")
        return _to_committee_job_out(job_row)

    @router.post(
        "/api/portfolios/{portfolio_id}/committee-analysis/{job_id}/confirm",
        response_model=CommitteeJobOut,
    )
    def confirm_committee_budget(
        portfolio_id: UUID,
        job_id: UUID,
        payload: ConfirmBudgetRequest,
        request: Request,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> CommitteeJobOut:
        job_row = repository.get_committee_job(connection, job_id)
        if job_row is None or job_row[1] != portfolio_id:
            raise HTTPException(status_code=404, detail="Job not found")

        event = request.app.state.committee_confirmations.get(job_id)
        if job_row[4] != "awaiting_confirmation" or event is None:
            raise HTTPException(status_code=409, detail="Job is not awaiting confirmation")

        request.app.state.committee_confirmation_decisions[job_id] = payload.approve
        event.set()

        return _to_committee_job_out(job_row)

    return router
