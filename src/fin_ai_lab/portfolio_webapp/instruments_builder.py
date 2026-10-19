"""Loads what instruments.py needs from the database and turns its answers
into the API's shapes (portfolio-webapp-S12). Identity is global -- one
answer for every portfolio -- so a breakdown's assignment means the same
asset in the single-portfolio and all-portfolios views."""

from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

import duckdb

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.instrument_overrides import InstrumentOverride
from fin_ai_lab.portfolio_webapp.instruments import (
    BrokerInstrument,
    Decision,
    Identities,
    Suggestion,
    resolve,
    suggest,
)
from fin_ai_lab.portfolio_webapp.schemas import (
    InstrumentOut,
    InstrumentsOut,
    SuggestionOut,
    ValuationOut,
    ValuedPositionOut,
)

PRICE = Decimal("0.0001")


@dataclass(frozen=True)
class LinkState:
    instruments: list[BrokerInstrument]  # everything held now, every portfolio
    decisions: list[Decision]
    identities: Identities
    key_by_position: dict[UUID, str]  # current position id -> per-broker key
    portfolio_names: dict[str, list[str]]  # per-broker key -> who holds it


def load_link_state(connection: duckdb.DuckDBPyConnection) -> LinkState:
    instruments: dict[str, BrokerInstrument] = {}
    key_by_position: dict[UUID, str] = {}
    portfolio_names: dict[str, list[str]] = {}
    for portfolio, row in repository.list_current_positions(connection):
        key = repository.position_key(row)
        key_by_position[row[0]] = key
        holders = portfolio_names.setdefault(key, [])
        if portfolio[1] not in holders:
            holders.append(portfolio[1])
        instruments[key] = _merge(
            instruments.get(key),
            BrokerInstrument(
                key=key,
                broker=row[2],
                name=row[4],
                isin=row[5],
                symbol=row[6],
                figi=row[15],
                ticker=row[16],
                exchange_code=row[17],
            ),
        )
    decisions = repository.list_instrument_decisions(connection)
    return LinkState(
        instruments=list(instruments.values()),
        decisions=decisions,
        identities=resolve(instruments.values(), decisions),
        key_by_position=key_by_position,
        portfolio_names=portfolio_names,
    )


def unit_values(state: LinkState, positions: list[ValuedPositionOut]) -> dict[str, Decimal]:
    """Today's value of one unit in PLN per per-broker key -- the price
    evidence a suggestion is checked against."""
    sums: dict[str, tuple[Decimal, Decimal]] = {}
    for position in positions:
        key = state.key_by_position.get(position.position_id)
        if key is None or position.value is None or position.quantity <= 0:
            continue
        value, quantity = sums.get(key, (Decimal(0), Decimal(0)))
        sums[key] = (value + position.value, quantity + position.quantity)
    return {key: value / quantity for key, (value, quantity) in sums.items()}


def suggestions_in_scope(state: LinkState, positions: list[ValuedPositionOut]) -> list[Suggestion]:
    in_scope = {state.key_by_position.get(p.position_id) for p in positions}
    return suggest(
        [i for i in state.instruments if i.key in in_scope],
        state.identities,
        state.decisions,
        unit_values(state, positions),
    )


def build_instruments(
    state: LinkState,
    valuation: ValuationOut,
    overrides: dict[str, InstrumentOverride],
) -> InstrumentsOut:
    """The linking form's data: every held instrument with its asset, and
    the pairs waiting for the owner's answer. `valuation` must cover every
    portfolio -- identity is global. Also what prices each instrument and
    the owner's own entry for it (#285)."""
    prices = unit_values(state, valuation.positions)
    positions_by_key: dict[str, list[ValuedPositionOut]] = {}
    for position in valuation.positions:
        key = state.key_by_position.get(position.position_id)
        if key is not None:
            positions_by_key.setdefault(key, []).append(position)
    asset_names = {asset.instrument_key: asset.instrument_name for asset in valuation.assets}

    instruments = []
    for instrument in state.instruments:
        held = positions_by_key.get(instrument.key, [])
        asset_key = state.identities.asset_key(instrument.key)
        price = prices.get(instrument.key)
        override = overrides.get(instrument.key)
        instruments.append(
            InstrumentOut(
                key=instrument.key,
                asset_key=asset_key,
                asset_name=asset_names.get(asset_key, instrument.name),
                linked_by=state.identities.linked_by.get(instrument.key),
                name=instrument.name,
                broker=instrument.broker,
                isin=instrument.isin,
                symbol=instrument.symbol,
                ticker=instrument.ticker,
                exchange_code=instrument.exchange_code,
                figi=instrument.figi,
                asset_class=held[0].asset_class if held else "other",
                portfolio_names=state.portfolio_names.get(instrument.key, []),
                quantity=sum((p.quantity for p in held), Decimal(0)),
                unit_value=price.quantize(PRICE, ROUND_HALF_UP) if price is not None else None,
                is_manual=instrument.is_manual,
                yahoo_ticker=next((p.yahoo_ticker for p in held if p.yahoo_ticker), None),
                quote_currency=next(
                    (p.valued_quote_currency for p in held if p.valued_quote_currency), None
                ),
                has_quotes=any(p.price_date is not None for p in held),
                owner_yahoo_ticker=override.yahoo_ticker if override else None,
                owner_quote_currency=override.quote_currency if override else None,
            )
        )
    instruments.sort(key=lambda i: (i.asset_name.lower(), i.asset_key, i.broker, i.key))

    return InstrumentsOut(
        base_currency=valuation.base_currency,
        prices_as_of=valuation.prices_as_of,
        instruments=instruments,
        suggestions=[
            SuggestionOut(key_a=s.key_a, key_b=s.key_b, reasons=s.reasons)
            for s in suggestions_in_scope(state, valuation.positions)
        ],
    )


def _merge(known: BrokerInstrument | None, row: BrokerInstrument) -> BrokerInstrument:
    """The same per-broker key held in two portfolios: an identifier either
    row resolved counts (one import may have reached OpenFIGI, one not)."""
    if known is None:
        return row
    return replace(
        known,
        isin=known.isin or row.isin,
        symbol=known.symbol or row.symbol,
        figi=known.figi or row.figi,
        ticker=known.ticker or row.ticker,
        exchange_code=known.exchange_code or row.exchange_code,
    )
