"""Shares of the portfolio value by breakdown group."""

from uuid import UUID

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.api.common import (
    get_db,
    require_breakdown,
)
from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.breakdowns import (
    BUILTIN_ASSET_CLASS,
    BUILTIN_NAMES,
    BUILTIN_PREFIX,
)
from fin_ai_lab.portfolio_webapp.schemas import SharesOut
from fin_ai_lab.portfolio_webapp.shares_builder import ALL_PORTFOLIOS_NAME, build_shares


def build_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/shares", response_model=SharesOut)
    async def get_shares(
        breakdown: str = BUILTIN_ASSET_CLASS,
        portfolio_id: UUID | None = None,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> SharesOut:
        # One portfolio, or every portfolio when portfolio_id is left out --
        # the same two scopes as the valuation endpoints.
        if portfolio_id is not None:
            portfolio = repository.get_portfolio(connection, portfolio_id)
            if portfolio is None:
                raise HTTPException(status_code=404, detail="Portfolio not found")
            rows, root_name = [portfolio], portfolio[1]
        else:
            rows, root_name = repository.list_portfolios(connection), ALL_PORTFOLIOS_NAME

        builtin, stored = None, None
        if breakdown.startswith(BUILTIN_PREFIX):
            if breakdown not in BUILTIN_NAMES:
                raise HTTPException(status_code=422, detail=f"Nieznany podział: {breakdown}")
            builtin = breakdown
        else:
            try:
                breakdown_id = UUID(breakdown)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422, detail=f"Nieznany podział: {breakdown}"
                ) from exc
            stored = require_breakdown(connection, breakdown_id)

        return await build_shares(
            connection,
            rows,
            builtin=builtin,
            breakdown=stored,
            root_name=root_name,
            today=deps.today_provider(),
            closes_fetcher=deps.daily_closes_fetcher,
            fx_client=deps.fx_client_factory(),
        )

    return router
