from contextlib import asynccontextmanager
from pathlib import Path

import duckdb
from fastapi import Depends, FastAPI, Request

from fin_ai_lab.portfolio_webapp import db, repository
from fin_ai_lab.portfolio_webapp.repository import PortfolioRow
from fin_ai_lab.portfolio_webapp.schemas import PortfolioCreate, PortfolioOut


def create_app(db_path: Path = db.DEFAULT_DB_PATH) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = db.connect(db_path)
        yield
        app.state.db.close()

    app = FastAPI(title="Portfel", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/portfolios", response_model=list[PortfolioOut])
    def list_portfolios(
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> list[PortfolioOut]:
        return [_to_portfolio_out(row) for row in repository.list_portfolios(connection)]

    @app.post("/api/portfolios", response_model=PortfolioOut, status_code=201)
    def create_portfolio(
        payload: PortfolioCreate,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> PortfolioOut:
        row = repository.create_portfolio(
            connection,
            name=payload.name,
            broker=payload.broker,
            account_type=payload.account_type,
        )
        return _to_portfolio_out(row)

    return app


def _get_db(request: Request) -> duckdb.DuckDBPyConnection:
    return request.app.state.db


def _to_portfolio_out(row: PortfolioRow) -> PortfolioOut:
    id_, name, broker, account_type, created_at = row
    return PortfolioOut(
        id=id_, name=name, broker=broker, account_type=account_type, created_at=created_at
    )
