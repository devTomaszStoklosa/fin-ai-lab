"""Portfolio list, creation and deletion."""

from uuid import UUID

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.api.common import get_db
from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.repository import PortfolioRow
from fin_ai_lab.portfolio_webapp.schemas import (
    PortfolioCreate,
    PortfolioOut,
)


def _to_portfolio_out(row: PortfolioRow) -> PortfolioOut:
    id_, name, broker, account_type, created_at = row
    return PortfolioOut(
        id=id_, name=name, broker=broker, account_type=account_type, created_at=created_at
    )


def build_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/portfolios", response_model=list[PortfolioOut])
    def list_portfolios(
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> list[PortfolioOut]:
        return [_to_portfolio_out(row) for row in repository.list_portfolios(connection)]

    @router.post("/api/portfolios", response_model=PortfolioOut, status_code=201)
    def create_portfolio(
        payload: PortfolioCreate,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> PortfolioOut:
        row = repository.create_portfolio(
            connection,
            name=payload.name,
            broker=payload.broker,
            account_type=payload.account_type,
        )
        return _to_portfolio_out(row)

    @router.delete("/api/portfolios/{portfolio_id}", status_code=204)
    def delete_portfolio(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> None:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        repository.delete_portfolio(connection, portfolio_id)

    return router
