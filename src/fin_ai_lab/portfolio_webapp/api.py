import zipfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date as date_type
from pathlib import Path
from typing import get_args
from uuid import UUID

import duckdb
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from openpyxl.utils.exceptions import InvalidFileException

from fin_ai_lab.portfolio_webapp import db, repository
from fin_ai_lab.portfolio_webapp.repository import PortfolioRow, PositionRow, SnapshotRow
from fin_ai_lab.portfolio_webapp.schemas import (
    ImportResponse,
    PortfolioCreate,
    PortfolioOut,
    PositionOut,
    SnapshotOut,
)
from fin_ai_lab.portfolio_xray.canonical import AccountType
from fin_ai_lab.portfolio_xray.identification.openfigi import OpenFigiClient
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry
from fin_ai_lab.portfolio_xray.service import import_file


def create_app(
    db_path: Path = db.DEFAULT_DB_PATH,
    # Injected rather than constructed inline (SOLID/D): production gets a
    # real, network-calling client by default; tests substitute `lambda: None`
    # so importing a synthetic file never depends on the network, the same
    # guarantee P1's own tests already rely on for `openfigi_client=None`.
    openfigi_client_factory: Callable[[], OpenFigiClient | None] = OpenFigiClient,
) -> FastAPI:
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

    @app.post(
        "/api/portfolios/{portfolio_id}/import",
        response_model=ImportResponse,
        status_code=201,
    )
    async def import_portfolio_file(
        portfolio_id: UUID,
        file: UploadFile = File(...),
        valuation_date: str = Form(...),
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> ImportResponse:
        portfolio = repository.get_portfolio(connection, portfolio_id)
        if portfolio is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        try:
            parsed_date = date_type.fromisoformat(valuation_date)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail={"errors": [str(exc)], "warnings": []}
            ) from exc

        # portfolio[3] is account_type, stored free-text at creation time (S1);
        # a value outside P1's canonical AccountType would otherwise fail deep
        # inside Position construction with a raw ValidationError.
        account_type = portfolio[3]
        if account_type not in get_args(AccountType):
            account_type = "regular"

        # New registry/client per request, same as the CLI does per invocation
        # (cli.py's import_positions) -- picks up newly approved parser
        # configs (S3) immediately, no server restart needed.
        try:
            result = await import_file(
                await file.read(),
                valuation_date=parsed_date,
                account_type=account_type,
                market_currency="PLN",
                registry=ParserRegistry(),
                openfigi_client=openfigi_client_factory(),
            )
        except (zipfile.BadZipFile, InvalidFileException) as exc:
            # A CLI user already picked a file they know is an XTB export; a
            # browser upload has no such guarantee, so unlike the CLI (which
            # lets this propagate) the API turns "not actually a spreadsheet"
            # into the same clean error shape as an unmatched-but-valid one.
            raise HTTPException(
                status_code=422,
                detail={"errors": [f"Unreadable file: {exc}"], "warnings": []},
            ) from exc

        if result.errors:
            raise HTTPException(
                status_code=422,
                detail={"errors": result.errors, "warnings": result.warnings},
            )

        # The snapshot's broker is what was actually parsed, not the portfolio's
        # own broker label from S1 -- those can drift (e.g. mislabeled at
        # creation). Falls back to the portfolio's label only when a "known
        # format" import somehow yields zero positions.
        broker = result.positions[0].broker if result.positions else (portfolio[2] or "unknown")
        snapshot_row = repository.create_snapshot(
            connection, portfolio_id=portfolio_id, broker=broker, valuation_date=parsed_date
        )
        repository.insert_positions(
            connection, snapshot_id=snapshot_row[0], positions=result.positions
        )
        position_rows = repository.list_positions(connection, snapshot_row[0])

        return ImportResponse(
            snapshot=_to_snapshot_out(snapshot_row, position_rows),
            warnings=result.warnings,
        )

    @app.get("/api/portfolios/{portfolio_id}/snapshots", response_model=list[SnapshotOut])
    def list_snapshots(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(_get_db),
    ) -> list[SnapshotOut]:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        return [
            _to_snapshot_out(row, repository.list_positions(connection, row[0]))
            for row in repository.list_snapshots(connection, portfolio_id)
        ]

    return app


def _get_db(request: Request) -> duckdb.DuckDBPyConnection:
    return request.app.state.db


def _to_portfolio_out(row: PortfolioRow) -> PortfolioOut:
    id_, name, broker, account_type, created_at = row
    return PortfolioOut(
        id=id_, name=name, broker=broker, account_type=account_type, created_at=created_at
    )


def _to_position_out(row: PositionRow) -> PositionOut:
    (
        id_,
        _snapshot_id,
        broker,
        account_type,
        instrument_name,
        isin,
        symbol,
        asset_class,
        quantity,
        avg_cost,
        cost_currency,
        market_value,
        market_currency,
        valuation_date,
        resolution_status,
        figi,
        ticker,
        exchange_code,
        identification_rule,
    ) = row
    return PositionOut(
        id=id_,
        broker=broker,
        account_type=account_type,
        instrument_name=instrument_name,
        isin=isin,
        symbol=symbol,
        asset_class=asset_class,
        quantity=quantity,
        avg_cost=avg_cost,
        cost_currency=cost_currency,
        market_value=market_value,
        market_currency=market_currency,
        valuation_date=valuation_date,
        resolution_status=resolution_status,
        figi=figi,
        ticker=ticker,
        exchange_code=exchange_code,
        identification_rule=identification_rule,
    )


def _to_snapshot_out(row: SnapshotRow, position_rows: list[PositionRow]) -> SnapshotOut:
    id_, portfolio_id, broker, valuation_date, imported_at, date_min, date_max = row
    return SnapshotOut(
        id=id_,
        portfolio_id=portfolio_id,
        broker=broker,
        valuation_date=valuation_date,
        imported_at=imported_at,
        source_file_date_min=date_min,
        source_file_date_max=date_max,
        positions=[_to_position_out(p) for p in position_rows],
    )
