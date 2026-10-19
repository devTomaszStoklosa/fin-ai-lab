"""Dividend history (from the database) and forecast (from Yahoo)."""

from uuid import UUID

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.api.common import get_db
from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.dividend_forecast_builder import build_dividend_forecast
from fin_ai_lab.portfolio_webapp.dividends_builder import build_dividend_history
from fin_ai_lab.portfolio_webapp.repository import PortfolioRow
from fin_ai_lab.portfolio_webapp.schemas import (
    DividendForecastOut,
    DividendHistoryOut,
)


async def _dividend_forecast(
    deps: AppDeps, connection: duckdb.DuckDBPyConnection, portfolio_rows: list[PortfolioRow]
) -> DividendForecastOut:
    return await build_dividend_forecast(
        connection,
        portfolio_rows,
        today=deps.today_provider(),
        fx_client=deps.fx_client_factory(),
        dividends_fetcher=deps.dividends_fetcher,
        quote_currency_fetcher=deps.quote_currency_fetcher,
        closes_fetcher=deps.daily_closes_fetcher,
    )


def build_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/dividends/history", response_model=DividendHistoryOut)
    async def get_all_portfolios_dividend_history(
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> DividendHistoryOut:
        # #265: every portfolio together -- the start page's dividends card.
        return await build_dividend_history(
            connection,
            repository.list_portfolios(connection),
            today=deps.today_provider(),
            fx_client=deps.fx_client_factory(),
        )

    @router.get(
        "/api/portfolios/{portfolio_id}/dividends/history", response_model=DividendHistoryOut
    )
    async def get_portfolio_dividend_history(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> DividendHistoryOut:
        portfolio = repository.get_portfolio(connection, portfolio_id)
        if portfolio is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        return await build_dividend_history(
            connection, [portfolio], today=deps.today_provider(), fx_client=deps.fx_client_factory()
        )

    # #266: separate from the history -- it asks Yahoo and takes longer,
    # while the history comes from the database alone and shows at once.
    @router.get("/api/dividends/forecast", response_model=DividendForecastOut)
    async def get_all_portfolios_dividend_forecast(
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> DividendForecastOut:
        return await _dividend_forecast(deps, connection, repository.list_portfolios(connection))

    @router.get(
        "/api/portfolios/{portfolio_id}/dividends/forecast", response_model=DividendForecastOut
    )
    async def get_portfolio_dividend_forecast(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> DividendForecastOut:
        portfolio = repository.get_portfolio(connection, portfolio_id)
        if portfolio is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        return await _dividend_forecast(deps, connection, [portfolio])

    return router
