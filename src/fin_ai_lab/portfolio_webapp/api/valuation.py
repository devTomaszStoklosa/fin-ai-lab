"""Value history of one portfolio or all of them together."""

from uuid import UUID

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.api.common import get_db
from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.schemas import ValuationOut
from fin_ai_lab.portfolio_webapp.valuation_builder import build_valuation


def build_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/valuation", response_model=ValuationOut)
    async def get_all_portfolios_valuation(
        refresh: bool = False,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> ValuationOut:
        # Every portfolio on one day axis -- the start page's sum and chart.
        return await build_valuation(
            connection,
            repository.list_portfolios(connection),
            today=deps.today_provider(),
            refresh=refresh,
            closes_fetcher=deps.daily_closes_fetcher,
            fx_client=deps.fx_client_factory(),
        )

    @router.get("/api/portfolios/{portfolio_id}/valuation", response_model=ValuationOut)
    async def get_portfolio_valuation(
        portfolio_id: UUID,
        refresh: bool = False,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> ValuationOut:
        portfolio = repository.get_portfolio(connection, portfolio_id)
        if portfolio is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        return await build_valuation(
            connection,
            [portfolio],
            today=deps.today_provider(),
            refresh=refresh,
            closes_fetcher=deps.daily_closes_fetcher,
            fx_client=deps.fx_client_factory(),
        )

    return router
