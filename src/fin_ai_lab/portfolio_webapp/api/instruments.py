"""Instruments across portfolios: linking the same asset, detaching it, owner data."""

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.api.common import get_db
from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.benchmark import normalize_ticker
from fin_ai_lab.portfolio_webapp.instrument_overrides_builder import (
    UnknownYahooSymbolError,
    YahooUnavailableError,
    checked_override,
)
from fin_ai_lab.portfolio_webapp.instruments_builder import build_instruments, load_link_state
from fin_ai_lab.portfolio_webapp.schemas import (
    InstrumentDetachIn,
    InstrumentLinkIn,
    InstrumentOwnerDataIn,
    InstrumentsOut,
)
from fin_ai_lab.portfolio_webapp.valuation_builder import build_valuation


async def _instruments_out(deps: AppDeps, connection: duckdb.DuckDBPyConnection) -> InstrumentsOut:
    # Every portfolio, whatever screen asks: identity is global (S12).
    state = load_link_state(connection)
    valuation = await build_valuation(
        connection,
        repository.list_portfolios(connection),
        today=deps.today_provider(),
        refresh=False,
        closes_fetcher=deps.daily_closes_fetcher,
        fx_client=deps.fx_client_factory(),
        link_state=state,
    )
    return build_instruments(state, valuation, repository.list_instrument_overrides(connection))


def build_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/instruments", response_model=InstrumentsOut)
    async def get_instruments(
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> InstrumentsOut:
        return await _instruments_out(deps, connection)

    @router.post("/api/instruments/links", response_model=InstrumentsOut)
    async def decide_instrument_link(
        payload: InstrumentLinkIn,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> InstrumentsOut:
        # REQ-091: the owner's answer for one pair -- "the same" joins them
        # into one asset, "different" keeps them apart for good (even with a
        # shared FIGI) and stops suggesting the pair.
        if payload.key_a == payload.key_b:
            raise HTTPException(status_code=422, detail="Wybierz dwa różne instrumenty.")
        known = {i.key for i in load_link_state(connection).instruments}
        for key in (payload.key_a, payload.key_b):
            if key not in known:
                raise HTTPException(status_code=422, detail=f"Nieznany instrument: {key}")
        repository.set_instrument_decision(
            connection, key_a=payload.key_a, key_b=payload.key_b, same=payload.same
        )
        return await _instruments_out(deps, connection)

    @router.post("/api/instruments/detach", response_model=InstrumentsOut)
    async def detach_instrument(
        payload: InstrumentDetachIn,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> InstrumentsOut:
        # REQ-094: takes one instrument out of its asset; the rest of the
        # asset stays joined, even where only this one linked them.
        state = load_link_state(connection)
        if payload.key not in {i.key for i in state.instruments}:
            raise HTTPException(status_code=422, detail=f"Nieznany instrument: {payload.key}")
        asset_key = state.identities.asset_key(payload.key)
        others = [k for k in state.identities.members(asset_key) if k != payload.key]
        repository.delete_same_decisions(connection, payload.key)
        for other in others:
            repository.set_instrument_decision(
                connection, key_a=payload.key, key_b=other, same=False
            )
        after = load_link_state(connection).identities
        if len({after.asset_key(k) for k in others}) > 1:
            for other in others[1:]:
                repository.set_instrument_decision(
                    connection, key_a=others[0], key_b=other, same=True
                )
        return await _instruments_out(deps, connection)

    @router.post("/api/instruments/owner-data", response_model=InstrumentsOut)
    async def save_instrument_owner_data(
        payload: InstrumentOwnerDataIn,
        connection: duckdb.DuckDBPyConnection = Depends(get_db),
    ) -> InstrumentsOut:
        # #285: the owner's own Yahoo symbol and quote currency for one held
        # instrument; both empty clears the entry. A manual position is the
        # owner's own figure and is never priced from quotes.
        instrument = next(
            (i for i in load_link_state(connection).instruments if i.key == payload.key), None
        )
        if instrument is None:
            raise HTTPException(status_code=422, detail=f"Nieznany instrument: {payload.key}")
        if instrument.is_manual:
            raise HTTPException(
                status_code=422,
                detail="Pozycja ręczna ma własną wartość -- nie wycenia się jej z notowań.",
            )
        ticker = None
        if payload.yahoo_ticker is not None and payload.yahoo_ticker.strip():
            ticker = normalize_ticker(payload.yahoo_ticker)
            if ticker is None:
                raise HTTPException(
                    status_code=422,
                    detail="Nieprawidłowy symbol -- dozwolone litery, cyfry i znaki . ^ = -",
                )
        if ticker is None and payload.quote_currency is None:
            repository.delete_instrument_override(connection, payload.key)
            return await _instruments_out(deps, connection)
        try:
            override = await checked_override(
                payload.key,
                ticker,
                payload.quote_currency,
                today=deps.today_provider(),
                closes_fetcher=deps.daily_closes_fetcher,
                quote_currency_fetcher=deps.quote_currency_fetcher,
            )
        except UnknownYahooSymbolError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Yahoo nie zna symbolu {exc.ticker} -- sprawdź go na finance.yahoo.com.",
            ) from None
        except YahooUnavailableError:
            raise HTTPException(
                status_code=502, detail="Yahoo nie odpowiedziało -- spróbuj ponownie za chwilę."
            ) from None
        repository.save_instrument_override(connection, override)
        return await _instruments_out(deps, connection)

    return router
