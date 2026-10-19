"""Snapshots, manually entered positions and their manual valuations."""

import asyncio
from collections.abc import Callable
from datetime import date as date_type
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.api.common import (
    get_db,
    position_row_to_domain,
    resolve_account_type,
    to_position_out,
    to_snapshot_out,
)
from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.api.live_values import live_market_values
from fin_ai_lab.portfolio_webapp.manual_valuations import (
    ManualValuation,
    ValuationDateError,
    validate_purchase_date,
    validate_valuation_date,
)
from fin_ai_lab.portfolio_webapp.manual_valuations import market_value as manual_market_value
from fin_ai_lab.portfolio_webapp.repository import PortfolioRow, PositionRow
from fin_ai_lab.portfolio_webapp.schemas import (
    ManualValuationIn,
    ManualValuationOut,
    PositionCreate,
    PositionOut,
    SnapshotOut,
)
from fin_ai_lab.portfolio_xray.canonical import AccountType, Position
from fin_ai_lab.portfolio_xray.identification.openfigi import OpenFigiClient
from fin_ai_lab.portfolio_xray.metrics.price_history import to_yahoo_ticker


def _require_manual_position(
    connection: duckdb.DuckDBPyConnection, portfolio_id: UUID, position_id: UUID
) -> PortfolioRow:
    # 404s a position from a file import too (REQ-011 forbids editing it,
    # and the frontend never offers the action for one) -- not a path real
    # use reaches, just a defensive backstop.
    portfolio = repository.get_portfolio(connection, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    manual_snapshot = repository.find_manual_snapshot(connection, portfolio_id)
    position = repository.get_position(connection, position_id)
    if position is None or manual_snapshot is None or position[1] != manual_snapshot[0]:
        raise HTTPException(status_code=404, detail="Position not found")

    return portfolio


def _check_dates(rule: Callable[..., None], *args: object) -> None:
    # A date the owner can fix (#288) -- 422 with the rule's own message.
    try:
        rule(*args)
    except ValuationDateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _sync_manual_market_value(connection: duckdb.DuckDBPyConnection, position: PositionRow) -> None:
    # After a valuation changed: the stored value follows the latest one,
    # else the purchase price (#288).
    valuations = repository.list_manual_valuations(connection, position[0])
    assert position[9] is not None  # a manual position always has its purchase price
    repository.set_market_value(
        connection, position[0], manual_market_value(position[8], position[9], valuations)
    )


def _to_valuation_out(valuation: ManualValuation, quantity: Decimal) -> ManualValuationOut:
    return ManualValuationOut(
        valued_on=valuation.valued_on,
        unit_value=valuation.unit_value,
        value=(quantity * valuation.unit_value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    )


async def _build_manual_position(
    payload: PositionCreate,
    *,
    account_type: AccountType,
    market_value: Decimal,
    purchased_on: date_type,
    openfigi_client: OpenFigiClient | None,
    quote_currency_fetcher: Callable[[str], str | None],
) -> Position:
    position = Position(
        broker=repository.MANUAL_BROKER,
        account_type=account_type,
        instrument_name=payload.instrument_name,
        isin=payload.isin,
        symbol=payload.symbol,
        asset_class=payload.asset_class,
        quantity=payload.quantity,
        avg_cost=payload.avg_cost,
        cost_currency="PLN",
        market_value=market_value,
        market_currency="PLN",
        valuation_date=purchased_on,
    )
    return await _resolve_manual_identification(position, openfigi_client, quote_currency_fetcher)


async def _resolve_manual_identification(
    position: Position,
    openfigi_client: OpenFigiClient | None,
    quote_currency_fetcher: Callable[[str], str | None],
) -> Position:
    # Mirrors service.py's own (module-private) _resolve_identifications for
    # a single position -- same reasoning as _flag_injection_warnings: that
    # function is P1-private, portfolio_webapp may only reach its public
    # surface (docs/ARCHITECTURE.md rule 6).
    if openfigi_client is None or position.isin is None:
        return position
    identification = await openfigi_client.resolve_by_isin(position.isin, "PLN", None)
    quote_currency = None
    if identification.ticker is not None:
        yfinance_ticker = to_yahoo_ticker(identification.ticker, identification.exchange_code)
        try:
            quote_currency = await asyncio.to_thread(quote_currency_fetcher, yfinance_ticker)
        except Exception:
            # yfinance is unofficial and sometimes blocked (docs/DATA-SOURCES.md)
            # -- a failed lookup must not break saving the position.
            quote_currency = None
    return position.model_copy(
        update={
            "resolution_status": identification.status,
            "figi": identification.figi,
            "ticker": identification.ticker,
            "exchange_code": identification.exchange_code,
            "identification_rule": identification.identification_rule,
            "quote_currency": quote_currency,
        }
    )


def build_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/portfolios/{portfolio_id}/snapshots", response_model=list[SnapshotOut])
    async def list_snapshots(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> list[SnapshotOut]:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        result: list[SnapshotOut] = []
        for index, row in enumerate(repository.list_snapshots(connection, portfolio_id)):
            position_rows = repository.list_positions(connection, row[0])
            # Only the latest snapshot (index 0) represents "now" in the UI
            # -- older ones are history (S7) and keep showing what they
            # showed at import time, so only this one's positions get a
            # live-refreshed value (issue #190).
            if index == 0:
                live_values = await live_market_values(
                    [position_row_to_domain(p) for p in position_rows],
                    deps.price_ratio_fetcher,
                    deps.fx_client_factory(),
                    deps.today_provider(),
                )
                positions = [
                    to_position_out(p, live_market_value=live_value)
                    for p, live_value in zip(position_rows, live_values, strict=True)
                ]
            else:
                positions = [to_position_out(p) for p in position_rows]
            result.append(to_snapshot_out(row, positions))
        return result

    @router.get("/api/portfolios/{portfolio_id}/positions", response_model=list[PositionOut])
    def list_manual_positions(
        portfolio_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> list[PositionOut]:
        if repository.get_portfolio(connection, portfolio_id) is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        snapshot = repository.find_manual_snapshot(connection, portfolio_id)
        if snapshot is None:
            return []
        return [to_position_out(row) for row in repository.list_positions(connection, snapshot[0])]

    @router.post(
        "/api/portfolios/{portfolio_id}/positions", response_model=PositionOut, status_code=201
    )
    async def create_manual_position(
        portfolio_id: UUID,
        payload: PositionCreate,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> PositionOut:
        portfolio = repository.get_portfolio(connection, portfolio_id)
        if portfolio is None:
            raise HTTPException(status_code=404, detail="Portfolio not found")

        purchased_on = payload.purchased_on or deps.today_provider()
        _check_dates(validate_purchase_date, purchased_on, [], deps.today_provider())
        # Valued at cost on creation: no valuation exists yet (#288).
        position = await _build_manual_position(
            payload,
            account_type=resolve_account_type(portfolio),
            market_value=manual_market_value(payload.quantity, payload.avg_cost, []),
            purchased_on=purchased_on,
            openfigi_client=deps.openfigi_client_factory(),
            quote_currency_fetcher=deps.quote_currency_fetcher,
        )
        snapshot = repository.get_or_create_manual_snapshot(connection, portfolio_id)
        row = repository.insert_position(connection, snapshot_id=snapshot[0], position=position)
        return to_position_out(row)

    @router.put(
        "/api/portfolios/{portfolio_id}/positions/{position_id}", response_model=PositionOut
    )
    async def update_manual_position(
        portfolio_id: UUID,
        position_id: UUID,
        payload: PositionCreate,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> PositionOut:
        portfolio = _require_manual_position(connection, portfolio_id, position_id)
        stored = repository.get_position(connection, position_id)
        assert stored is not None
        valuations = repository.list_manual_valuations(connection, position_id)
        purchased_on = payload.purchased_on or stored[13]
        _check_dates(validate_purchase_date, purchased_on, valuations, deps.today_provider())

        # The value follows the owner's valuations (#288), per unit -- a new
        # quantity scales it, a new purchase price matters only without one.
        position = await _build_manual_position(
            payload,
            account_type=resolve_account_type(portfolio),
            market_value=manual_market_value(payload.quantity, payload.avg_cost, valuations),
            purchased_on=purchased_on,
            openfigi_client=deps.openfigi_client_factory(),
            quote_currency_fetcher=deps.quote_currency_fetcher,
        )
        row = repository.update_position(connection, position_id=position_id, position=position)
        return to_position_out(row)

    @router.delete("/api/portfolios/{portfolio_id}/positions/{position_id}", status_code=204)
    def delete_manual_position(
        portfolio_id: UUID,
        position_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> None:
        _require_manual_position(connection, portfolio_id, position_id)
        repository.delete_position(connection, position_id)

    @router.get(
        "/api/portfolios/{portfolio_id}/positions/{position_id}/valuations",
        response_model=list[ManualValuationOut],
    )
    def list_manual_valuations(
        portfolio_id: UUID,
        position_id: UUID,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> list[ManualValuationOut]:
        _require_manual_position(connection, portfolio_id, position_id)
        position = repository.get_position(connection, position_id)
        assert position is not None
        return [
            _to_valuation_out(valuation, position[8])
            for valuation in repository.list_manual_valuations(connection, position_id)
        ]

    @router.put(
        "/api/portfolios/{portfolio_id}/positions/{position_id}/valuations/{valued_on}",
        response_model=ManualValuationOut,
    )
    def save_manual_valuation(
        portfolio_id: UUID,
        position_id: UUID,
        valued_on: date_type,
        payload: ManualValuationIn,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> ManualValuationOut:
        # PUT on the day itself: a second valuation of the same day replaces
        # the first, the same request twice changes nothing more (#288).
        _require_manual_position(connection, portfolio_id, position_id)
        position = repository.get_position(connection, position_id)
        assert position is not None
        _check_dates(validate_valuation_date, valued_on, position[13], deps.today_provider())

        valuation = ManualValuation(valued_on=valued_on, unit_value=payload.unit_value)
        repository.save_manual_valuation(connection, position_id, valuation)
        _sync_manual_market_value(connection, position)
        return _to_valuation_out(valuation, position[8])

    @router.delete(
        "/api/portfolios/{portfolio_id}/positions/{position_id}/valuations/{valued_on}",
        status_code=204,
    )
    def delete_manual_valuation(
        portfolio_id: UUID,
        position_id: UUID,
        valued_on: date_type,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> None:
        _require_manual_position(connection, portfolio_id, position_id)
        position = repository.get_position(connection, position_id)
        assert position is not None
        valuations = repository.list_manual_valuations(connection, position_id)
        if all(valuation.valued_on != valued_on for valuation in valuations):
            raise HTTPException(status_code=404, detail="Valuation not found")

        repository.delete_manual_valuation(connection, position_id, valued_on)
        _sync_manual_market_value(connection, position)

    return router
