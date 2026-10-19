"""Helpers shared by the routers."""

from datetime import date as date_type
from decimal import ROUND_HALF_UP, Decimal
from typing import cast, get_args
from uuid import UUID

import duckdb
from fastapi import HTTPException, Request
from google.genai import errors as genai_errors

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.breakdowns import Breakdown
from fin_ai_lab.portfolio_webapp.repository import PortfolioRow, PositionRow, SnapshotRow
from fin_ai_lab.portfolio_webapp.schemas import (
    PositionOut,
    SnapshotOut,
)
from fin_ai_lab.portfolio_xray.canonical import AccountType, Position
from fin_ai_lab.portfolio_xray.metrics.fx import NbpFxClient, convert_to_base_currency


def llm_unavailable(exc: genai_errors.APIError) -> HTTPException:
    # Covers both ServerError (5xx, e.g. "model overloaded") and ClientError
    # (4xx, e.g. Gemini's own rate limit) -- either way the report can't be
    # generated right now, and the raw exception must not reach the owner as
    # an opaque 500 (issue #204).
    return HTTPException(
        status_code=503,
        detail=f"Model AI chwilowo niedostępny ({exc.message}) -- spróbuj ponownie za chwilę.",
    )


def resolve_account_type(portfolio: PortfolioRow) -> AccountType:
    # portfolio[3] is account_type, stored free-text at creation time (S1);
    # a value outside P1's canonical AccountType would otherwise fail deep
    # inside Position construction with a raw ValidationError.
    account_type = portfolio[3]
    if account_type not in get_args(AccountType):
        return "regular"
    return cast(AccountType, account_type)


def get_db(request: Request) -> duckdb.DuckDBPyConnection:
    # cursor(), not the shared connection directly: FastAPI runs sync
    # endpoints in a threadpool, and concurrent execute() calls on one
    # DuckDB connection from different threads corrupt each other's result
    # rows (reproduced). cursor() shares the same database but is
    # independent per call.
    return request.app.state.db.cursor()


def to_position_out(row: PositionRow, *, live_market_value: Decimal | None = None) -> PositionOut:
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
        quote_currency,
    ) = row
    effective_market_value = market_value if live_market_value is None else live_market_value
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
        market_value=effective_market_value,
        market_currency=market_currency,
        valuation_date=valuation_date,
        resolution_status=resolution_status,
        figi=figi,
        ticker=ticker,
        exchange_code=exchange_code,
        identification_rule=identification_rule,
        quote_currency=quote_currency,
        return_pct=_return_pct(
            quantity=quantity,
            avg_cost=avg_cost,
            cost_currency=cost_currency,
            market_value=effective_market_value,
            market_currency=market_currency,
        ),
    )


def _return_pct(
    *,
    quantity: Decimal,
    avg_cost: Decimal | None,
    cost_currency: str | None,
    market_value: Decimal | None,
    market_currency: str | None,
) -> Decimal | None:
    # Short/derivative positions (quantity <= 0) need a sign-aware formula --
    # the naive one below would report a loss as a gain -- out of scope here.
    if avg_cost is None or market_value is None or quantity <= 0:
        return None
    if cost_currency != market_currency:
        return None

    cost_basis = quantity * avg_cost
    if cost_basis == 0:
        return None

    return ((market_value - cost_basis) / cost_basis * 100).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )


def position_row_to_domain(row: PositionRow) -> Position:
    return repository.row_to_position(row)


def to_snapshot_out(row: SnapshotRow, positions: list[PositionOut]) -> SnapshotOut:
    id_, portfolio_id, broker, valuation_date, imported_at, date_min, date_max = row
    return SnapshotOut(
        id=id_,
        portfolio_id=portfolio_id,
        broker=broker,
        valuation_date=valuation_date,
        imported_at=imported_at,
        source_file_date_min=date_min,
        source_file_date_max=date_max,
        positions=positions,
    )


def current_position_rows(
    connection: duckdb.DuckDBPyConnection, portfolio_id: UUID
) -> list[PositionRow]:
    # Same "current state" as PortfolioDetail.tsx's own merge (S4): the
    # latest real import, if any, plus every manually added position.
    rows: list[PositionRow] = []
    snapshots = repository.list_snapshots(connection, portfolio_id)
    if snapshots:
        rows.extend(repository.list_positions(connection, snapshots[0][0]))
    manual_snapshot = repository.find_manual_snapshot(connection, portfolio_id)
    if manual_snapshot is not None:
        rows.extend(repository.list_positions(connection, manual_snapshot[0]))
    return rows


async def base_currency_value(position: Position, fx_client: NbpFxClient) -> Decimal:
    # Mirrors report/orchestrator.py's own (module-private) base_currency_value
    # -- same reasoning as _flag_injection_warnings: P1-private, portfolio_webapp
    # may only reach its public surface (docs/ARCHITECTURE.md rule 6).
    if position.market_value is None or position.market_currency is None:
        return Decimal(0)
    return await convert_to_base_currency(
        position.market_value, position.market_currency, position.valuation_date, fx_client
    )


def require_breakdown(connection: duckdb.DuckDBPyConnection, breakdown_id: UUID) -> Breakdown:
    breakdown = repository.get_breakdown(connection, breakdown_id)
    if breakdown is None:
        raise HTTPException(status_code=404, detail="Breakdown not found")
    return breakdown


def current_reporting_context(
    connection: duckdb.DuckDBPyConnection, portfolio_id: UUID
) -> tuple[UUID, date_type] | None:
    # The snapshot id a report gets cached against, and the valuation date
    # put in front of the LLM -- the latest real import if one exists
    # (its own valuation_date), else the manual-positions container (dated
    # today, since manual positions don't carry one collective date).
    # Editing a manual position afterwards doesn't change this id, so a
    # cached report can go stale until the owner clicks "Odśwież" --
    # accepted trade-off (REQ-041 already provides that escape hatch).
    snapshots = repository.list_snapshots(connection, portfolio_id)
    if snapshots:
        return snapshots[0][0], snapshots[0][3]
    manual_snapshot = repository.find_manual_snapshot(connection, portfolio_id)
    if manual_snapshot is not None:
        return manual_snapshot[0], date_type.today()
    return None
