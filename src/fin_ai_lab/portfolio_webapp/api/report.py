"""The AI portfolio report: cached read and (re)generation."""

import asyncio
from decimal import Decimal
from uuid import UUID

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Request
from google.genai import errors as genai_errors

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.api.common import (
    base_currency_value,
    current_position_rows,
    current_reporting_context,
    get_db,
    llm_unavailable,
    position_row_to_domain,
)
from fin_ai_lab.portfolio_webapp.api.defaults import (
    BASE_CURRENCY,
    MODEL,
)
from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.schemas import ReportOut
from fin_ai_lab.portfolio_xray.metrics.weights import compute_weights
from fin_ai_lab.portfolio_xray.report.builder import ReportRejectedError, build_report
from fin_ai_lab.portfolio_xray.report.models import InstrumentMetadata, MetricsJson
from fin_ai_lab.portfolio_xray.sectors.classifier import classify_sector


def _to_report_out(row: repository.ReportRow) -> ReportOut:
    id_, snapshot_id, generated_at, model, cost_usd, content_md = row
    return ReportOut(
        id=id_,
        snapshot_id=snapshot_id,
        generated_at=generated_at,
        model=model,
        cost_usd=cost_usd,
        content_md=content_md,
    )


def build_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/api/portfolios/{portfolio_id}/report",
        response_model=ReportOut | None,
    )
    def get_cached_report(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> ReportOut | None:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        context = current_reporting_context(connection, portfolio_id)
        if context is None:
            return None
        snapshot_id, _valuation_date = context
        cached = repository.find_latest_report(connection, snapshot_id)
        return _to_report_out(cached) if cached is not None else None

    @router.post("/api/portfolios/{portfolio_id}/report", response_model=ReportOut)
    async def generate_portfolio_report(
        portfolio_id: UUID,
        request: Request,
        regenerate: bool = False,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> ReportOut:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        context = current_reporting_context(connection, portfolio_id)
        if context is None:
            raise HTTPException(status_code=422, detail="Portfolio has no positions yet")
        snapshot_id, valuation_date = context

        lock = request.app.state.report_locks.setdefault(portfolio_id, asyncio.Lock())
        async with lock:
            if not regenerate:
                cached = repository.find_latest_report(connection, snapshot_id)
                if cached is not None:
                    return _to_report_out(cached)

            rows = current_position_rows(connection, portfolio_id)
            positions = [position_row_to_domain(row) for row in rows]
            fx_client = deps.fx_client_factory()
            positions_with_base_value = [
                (position, await base_currency_value(position, fx_client)) for position in positions
            ]
            try:
                weights = compute_weights(positions_with_base_value)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

            llm_client = deps.llm_client_factory()
            prompt_registry = request.app.state.prompt_registry
            cost_before = llm_client.total_cost_usd

            instrument_metadata: dict[str, InstrumentMetadata] = {}
            category_weight: dict[str, Decimal] = {}
            try:
                for index, weighted in enumerate(weights.weighted_positions):
                    key = str(index)
                    category = await classify_sector(
                        weighted.position, llm_client, prompt_registry, MODEL
                    )
                    category_weight[category] = (
                        category_weight.get(category, Decimal(0)) + weighted.weight
                    )
                    instrument_metadata[key] = InstrumentMetadata(
                        name=weighted.position.instrument_name,
                        category=category,
                        exchange_code=weighted.position.exchange_code,
                        currency=weighted.position.market_currency,
                    )
            except genai_errors.APIError as exc:
                raise llm_unavailable(exc) from exc

            metrics = MetricsJson(
                valuation_date=valuation_date,
                base_currency=BASE_CURRENCY,
                weights=weights,
                risk=None,  # metrics/risk.py needs yfinance history -- out of scope (S5/S6)
                allocation_by_category=category_weight,
            )

            try:
                content_md = await build_report(
                    metrics, instrument_metadata, llm_client, prompt_registry, MODEL
                )
            except ReportRejectedError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except genai_errors.APIError as exc:
                raise llm_unavailable(exc) from exc

            cost_usd = llm_client.total_cost_usd - cost_before
            row = repository.create_report(
                connection,
                snapshot_id=snapshot_id,
                model=MODEL,
                cost_usd=cost_usd,
                content_md=content_md,
            )
            return _to_report_out(row)

    return router
