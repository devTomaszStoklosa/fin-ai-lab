"""Aggregators: user-defined sums of instruments within a portfolio."""

from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.aggregators import (
    Aggregator,
    CycleError,
    instrument_key,
    resolve_value,
    validate_no_cycle,
)
from fin_ai_lab.portfolio_webapp.api.common import (
    base_currency_value,
    current_position_rows,
    get_db,
    position_row_to_domain,
)
from fin_ai_lab.portfolio_webapp.api.defaults import BASE_CURRENCY
from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.schemas import (
    AggregatorCreate,
    AggregatorOut,
)
from fin_ai_lab.portfolio_xray.metrics.fx import NbpFxClient


async def _instrument_values_by_key(
    connection: duckdb.DuckDBPyConnection, portfolio_id: UUID, fx_client: NbpFxClient
) -> dict[str, Decimal]:
    # Live, non-live-price-refreshed value on purpose -- aggregators sum
    # whatever the portfolio's positions already show (same stored value
    # metrics.py would use before #190's live-refresh, kept simple here:
    # an aggregate is a grouping/display concern, not itself a live quote).
    values: dict[str, Decimal] = {}
    for row in current_position_rows(connection, portfolio_id):
        position = position_row_to_domain(row)
        key = instrument_key(position)
        values[key] = values.get(key, Decimal(0)) + await base_currency_value(position, fx_client)
    return values


def _to_aggregator_out(
    aggregator: Aggregator,
    all_by_id: dict[UUID, Aggregator],
    values_by_key: dict[str, Decimal],
) -> AggregatorOut:
    value = resolve_value(aggregator, all_by_id, values_by_key)
    return AggregatorOut(
        id=aggregator.id,
        portfolio_id=aggregator.portfolio_id,
        name=aggregator.name,
        member_instrument_keys=aggregator.member_instrument_keys,
        member_aggregator_ids=aggregator.member_aggregator_ids,
        value=value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        base_currency=BASE_CURRENCY,
    )


def _require_existing_aggregators(
    connection: duckdb.DuckDBPyConnection, portfolio_id: UUID, member_aggregator_ids: list[UUID]
) -> None:
    existing_ids = {a.id for a in repository.list_aggregators(connection, portfolio_id)}
    unknown = [str(mid) for mid in member_aggregator_ids if mid not in existing_ids]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown aggregator id(s) in this portfolio: {', '.join(unknown)}",
        )


def _require_own_aggregator(
    connection: duckdb.DuckDBPyConnection, portfolio_id: UUID, aggregator_id: UUID
) -> Aggregator:
    aggregator = repository.get_aggregator(connection, aggregator_id)
    if aggregator is None or aggregator.portfolio_id != portfolio_id:
        raise HTTPException(status_code=404, detail="Aggregator not found")
    return aggregator


def build_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/portfolios/{portfolio_id}/aggregators", response_model=list[AggregatorOut])
    async def list_portfolio_aggregators(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> list[AggregatorOut]:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        all_aggregators = repository.list_aggregators(connection, portfolio_id)
        all_by_id = {a.id: a for a in all_aggregators}
        values_by_key = await _instrument_values_by_key(
            connection, portfolio_id, deps.fx_client_factory()
        )
        return [_to_aggregator_out(a, all_by_id, values_by_key) for a in all_aggregators]

    @router.post(
        "/api/portfolios/{portfolio_id}/aggregators",
        response_model=AggregatorOut,
        status_code=201,
    )
    async def create_portfolio_aggregator(
        portfolio_id: UUID,
        payload: AggregatorCreate,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> AggregatorOut:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        _require_existing_aggregators(connection, portfolio_id, payload.member_aggregator_ids)

        created = repository.create_aggregator(
            connection,
            portfolio_id=portfolio_id,
            name=payload.name,
            member_instrument_keys=payload.member_instrument_keys,
            member_aggregator_ids=payload.member_aggregator_ids,
        )
        all_aggregators = repository.list_aggregators(connection, portfolio_id)
        all_by_id = {a.id: a for a in all_aggregators}
        values_by_key = await _instrument_values_by_key(
            connection, portfolio_id, deps.fx_client_factory()
        )
        return _to_aggregator_out(created, all_by_id, values_by_key)

    @router.put(
        "/api/portfolios/{portfolio_id}/aggregators/{aggregator_id}",
        response_model=AggregatorOut,
    )
    async def update_portfolio_aggregator(
        portfolio_id: UUID,
        aggregator_id: UUID,
        payload: AggregatorCreate,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> AggregatorOut:
        _require_own_aggregator(connection, portfolio_id, aggregator_id)
        _require_existing_aggregators(connection, portfolio_id, payload.member_aggregator_ids)

        all_aggregators = repository.list_aggregators(connection, portfolio_id)
        all_by_id = {a.id: a for a in all_aggregators}
        try:
            validate_no_cycle(aggregator_id, payload.member_aggregator_ids, all_by_id)
        except CycleError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        updated = repository.update_aggregator(
            connection,
            aggregator_id=aggregator_id,
            name=payload.name,
            member_instrument_keys=payload.member_instrument_keys,
            member_aggregator_ids=payload.member_aggregator_ids,
        )
        all_by_id[aggregator_id] = updated
        values_by_key = await _instrument_values_by_key(
            connection, portfolio_id, deps.fx_client_factory()
        )
        return _to_aggregator_out(updated, all_by_id, values_by_key)

    @router.delete(
        "/api/portfolios/{portfolio_id}/aggregators/{aggregator_id}",
        status_code=204,
    )
    def delete_portfolio_aggregator(
        portfolio_id: UUID,
        aggregator_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> None:
        _require_own_aggregator(connection, portfolio_id, aggregator_id)
        repository.delete_aggregator(connection, aggregator_id)

    return router
