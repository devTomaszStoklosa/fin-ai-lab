"""Day-by-day portfolio value (portfolio-webapp-S10) -- pure computation:
no database, no network, every amount a Decimal. api.py gathers the inputs
(holdings from snapshots/lots/ledger, closes from yfinance, NBP rates) and
hands them here, so each rule below is testable on hand-made numbers.

Two independent questions, answered separately:
1. How many units of each instrument were held on day d? (quantities_*)
2. What was one unit worth on day d, in PLN? (unit_value_series)
The value on day d is simply the product, summed over instruments.
"""

from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

BASE_CURRENCY = "PLN"

# Yahoo quotes some London listings in pence ("GBp"/"GBX") -- for an FX
# *ratio* (the only way FX is used below) pence and pounds move identically,
# so both map to GBP's NBP rate. Only shapes observed from yfinance here.
_QUOTE_CURRENCY_ALIASES = {"GBp": "GBP", "GBX": "GBP"}


def fx_currency_code(currency: str) -> str:
    """The NBP code a quote currency moves with (pence -> pounds)."""
    return _QUOTE_CURRENCY_ALIASES.get(currency, currency)


@dataclass(frozen=True)
class Lot:
    quantity: Decimal
    opened_on: date


@dataclass(frozen=True)
class SnapshotHoldings:
    """One import's state: quantity per instrument key, plus the lots behind
    a quantity where the broker's export dated them (XTB)."""

    valuation_date: date
    quantities: dict[str, Decimal]
    lots: dict[str, list[Lot]] = field(default_factory=dict)


@dataclass(frozen=True)
class QuantityChange:
    """A signed change of one instrument's quantity on one day -- a ledger
    transaction (Bossa), or a manual position appearing on its entry date."""

    key: str
    on: date
    quantity_change: Decimal


@dataclass(frozen=True)
class Anchor:
    """A known value of one unit at one date -- the stored market value of
    the most recent import holding the instrument. Every other day is this
    value moved by the instrument's own price ratio (and FX ratio), the
    same "ratio, never an absolute foreign price" rule as P1's
    price_change_ratio (issue #188), so the quote's unit (USD, GBp...) never
    has to be trusted as if it were the account's currency."""

    unit_value: Decimal  # in `currency`
    currency: str  # the currency the broker recorded the value in
    as_of: date
    quote_currency: str | None = None  # the instrument's own trading currency
    # False for a manual position: the owner's own figure, never moved by
    # market data (same rule as api.py's _live_price_ratio).
    moves_with_market: bool = True
    # The owner's own later values of one unit (#288), in `currency`: from
    # each day on the unit is worth that value instead -- a manual position
    # revalued by hand. Only used when the unit doesn't move with closes.
    revaluations: tuple[tuple[date, Decimal], ...] = ()


@dataclass(frozen=True)
class UnitValues:
    native: list[Decimal]  # per day, in anchor.currency
    base: list[Decimal]  # per day, in PLN
    last_price_date: date | None  # last real close used, None if no closes
    # Quote currency whose NBP series was missing -- its FX factor was then
    # left out (the price ratio alone still moves the value).
    missing_quote_fx: str | None = None


def day_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def quantities_from_snapshots(
    snapshots: list[SnapshotHoldings], days: list[date]
) -> dict[str, list[Decimal]]:
    """Quantity per instrument per day for a broker whose export is a state,
    not a ledger (XTB). On day d:

    - the latest import dated on or before d is the base (held as-is until
      the next import says otherwise -- a sale between two imports shows up
      on the later import's date, the only date the data can prove);
    - plus every lot a *later* import dates between that base import and d:
      it was bought after the base was taken, so it can't already be in the
      base, and it was still open at the later import, so it was held on d.

    Before the first import there is no base, so only dated lots count --
    which is what lets the history start before the first import at all.
    Lots opened and closed entirely between two imports are invisible here;
    the export doesn't state them.

    Base + new lots is capped at the larger of the two imports around d: if
    it's more than both, part of the base was sold in between (a sell and
    rebuy), on a day the exports don't state -- the cap keeps the history
    from inventing a peak neither import ever showed.
    """
    ordered = sorted(snapshots, key=lambda s: s.valuation_date)
    snapshot_dates = [s.valuation_date for s in ordered]
    keys = sorted({key for s in ordered for key in [*s.quantities, *s.lots]})
    result = {key: [Decimal(0)] * len(days) for key in keys}

    for index, day in enumerate(days):
        base_position = bisect_right(snapshot_dates, day) - 1
        base = ordered[base_position] if base_position >= 0 else None
        later = ordered[base_position + 1 :]
        for key in keys:
            quantity = base.quantities.get(key, Decimal(0)) if base is not None else Decimal(0)
            dated_by = next((s for s in later if key in s.lots), None)
            if dated_by is not None:
                quantity += sum(
                    (
                        lot.quantity
                        for lot in dated_by.lots[key]
                        if lot.opened_on <= day
                        and (base is None or lot.opened_on > base.valuation_date)
                    ),
                    Decimal(0),
                )
                if base is not None:
                    base_quantity = base.quantities.get(key, Decimal(0))
                    next_quantity = later[0].quantities.get(key, Decimal(0))
                    quantity = min(quantity, max(base_quantity, next_quantity))
            result[key][index] = quantity
    return result


def quantities_from_changes(
    changes: list[QuantityChange], days: list[date]
) -> dict[str, list[Decimal]]:
    """Running sum of signed changes per instrument -- exact for a ledger.
    A running total below zero means the imported history has a gap before
    its first transaction (ledger.py raises on it for the current state);
    for a past day it is shown as 0, never as a negative holding."""
    by_key: dict[str, list[QuantityChange]] = {}
    for change in changes:
        by_key.setdefault(change.key, []).append(change)

    result: dict[str, list[Decimal]] = {}
    for key, key_changes in by_key.items():
        ordered = sorted(key_changes, key=lambda c: c.on)
        series: list[Decimal] = []
        running = Decimal(0)
        cursor = 0
        for day in days:
            while cursor < len(ordered) and ordered[cursor].on <= day:
                running += ordered[cursor].quantity_change
                cursor += 1
            series.append(max(running, Decimal(0)))
        result[key] = series
    return result


def unit_value_series(
    anchor: Anchor,
    days: list[date],
    closes: dict[date, Decimal] | None,
    fx_rates: dict[str, dict[date, Decimal]],
) -> UnitValues:
    """Value of one unit on each day, in the anchor's currency and in PLN.

    unit(d) = unit(v) * close(d)/close(v) [* FXq(d)/FXq(v) / (FXm(d)/FXm(v))]
    where v is the anchor date, q the quote currency and m the currency the
    broker recorded the value in. The FX factor only applies when q != m,
    e.g. a USD stock held in a PLN account moves with USD/PLN too. Without
    closes the unit keeps its anchor value (a manual position, an
    unresolved ticker) -- or, from the day of each of the owner's
    revaluations on, that revaluation's value, as a step: nothing between
    two known values is invented. A missing FX series drops only that
    factor. Weekends and holidays reuse the last close/rate on or before
    the day.
    """
    market_currency = anchor.currency
    quote_currency = _QUOTE_CURRENCY_ALIASES.get(
        anchor.quote_currency or "", anchor.quote_currency or market_currency
    )

    market_fx = _series_or_none(market_currency, fx_rates)
    if market_fx is None:
        # Without m->PLN there is no PLN value at all; the anchor day's own
        # rate would be a guess dressed up as data.
        raise MissingFxRateError(market_currency)

    use_closes = anchor.moves_with_market and bool(closes)
    quote_fx = None
    missing_quote_fx = None
    if use_closes and quote_currency != market_currency:
        quote_fx = _series_or_none(quote_currency, fx_rates)
        if quote_fx is None:
            missing_quote_fx = quote_currency

    closes_lookup = _AsOfLookup(closes) if use_closes and closes else None
    # The anchor itself is the first known value, so a day before the
    # first revaluation keeps it; a revaluation on the anchor's own day wins.
    owner_lookup = (
        _AsOfLookup({anchor.as_of: anchor.unit_value, **dict(anchor.revaluations)})
        if anchor.revaluations and closes_lookup is None
        else None
    )
    market_lookup = _AsOfLookup(market_fx) if market_fx else None
    quote_lookup = _AsOfLookup(quote_fx) if quote_fx else None

    anchor_close = closes_lookup.at(anchor.as_of) if closes_lookup else None
    anchor_market_fx = market_lookup.at(anchor.as_of) if market_lookup else Decimal(1)
    anchor_quote_fx = quote_lookup.at(anchor.as_of) if quote_lookup else None

    native: list[Decimal] = []
    base: list[Decimal] = []
    for day in days:
        market_rate = market_lookup.at(day) if market_lookup else Decimal(1)
        unit = owner_lookup.at(day) if owner_lookup is not None else anchor.unit_value
        if closes_lookup is not None and anchor_close:
            unit = unit * closes_lookup.at(day) / anchor_close
            if quote_lookup is not None and anchor_quote_fx:
                quote_move = quote_lookup.at(day) / anchor_quote_fx
                market_move = market_rate / anchor_market_fx
                unit = unit * quote_move / market_move
        native.append(unit)
        base.append(unit * market_rate)

    last_price_date = closes_lookup.last_on_or_before(days[-1]) if closes_lookup and days else None
    return UnitValues(
        native=native,
        base=base,
        last_price_date=last_price_date,
        missing_quote_fx=missing_quote_fx,
    )


def fx_move(
    market_currency: str,
    quote_currency: str | None,
    since: date,
    until: date,
    fx_rates: dict[str, dict[date, Decimal]],
) -> Decimal:
    """How much a value recorded in `market_currency` moves from `since` to
    `until` because the instrument trades in `quote_currency`:
    FXq(until)/FXq(since) / (FXm(until)/FXm(since)) -- unit_value_series'
    FX factor for one day, for a caller that needs no series (api.py's live
    value, #283). 1 when both are the same currency (pence move with
    pounds) or the quote currency is unknown. Raises MissingFxRateError
    when either series is missing: the caller decides what to leave out."""
    quote_code = fx_currency_code(quote_currency) if quote_currency else market_currency
    if quote_code == market_currency:
        return Decimal(1)
    quote_rate = base_rate_lookup(quote_code, fx_rates)
    market_rate = base_rate_lookup(market_currency, fx_rates)
    quote_change = quote_rate(until) / quote_rate(since)
    market_change = market_rate(until) / market_rate(since)
    return quote_change / market_change


def value_series(
    quantities: dict[str, list[Decimal]], unit_values: dict[str, list[Decimal]], length: int
) -> list[Decimal]:
    """Sum of quantity x unit value per day, over instruments that have a
    unit value at all (an instrument without one is reported by the caller,
    not silently valued at zero here)."""
    totals = [Decimal(0)] * length
    for key, key_quantities in quantities.items():
        key_units = unit_values.get(key)
        if key_units is None:
            continue
        for index in range(length):
            if key_quantities[index]:
                totals[index] += key_quantities[index] * key_units[index]
    return totals


def prior_holdings_value_series(
    quantities: dict[str, list[Decimal]], unit_values: dict[str, list[Decimal]], length: int
) -> list[Decimal]:
    """Value on day d of what was held at the end of day d-1, at day d's
    unit values -- what the portfolio would be worth on d had nothing been
    bought or sold that day (fin-ai-lab#273). Set against the value of d-1,
    it is the day's return from prices alone. The first day has no day
    before it: 0. Same rule as value_series for an instrument without a
    unit value: left out of both."""
    totals = [Decimal(0)] * length
    for key, key_quantities in quantities.items():
        key_units = unit_values.get(key)
        if key_units is None:
            continue
        for index in range(1, length):
            if key_quantities[index - 1]:
                totals[index] += key_quantities[index - 1] * key_units[index]
    return totals


def return_index(
    values: list[Decimal], prior_holdings_values: list[Decimal], dividends: list[Decimal]
) -> list[Decimal]:
    """What 1 held on the first day grew to, day by day, with deposits,
    purchases and sales left out -- the time-weighted return the benchmark
    comparison sets against an index (fin-ai-lab#273). Each day's factor is
    (yesterday's holdings at today's prices + dividends credited today) /
    yesterday's value, and the factors multiply. A day after an empty one
    (nothing held, nothing to grow) keeps the index where it was."""
    index = [Decimal(1)] * len(values)
    for day in range(1, len(values)):
        previous = values[day - 1]
        factor = (
            (prior_holdings_values[day] + dividends[day]) / previous if previous > 0 else Decimal(1)
        )
        index[day] = index[day - 1] * factor
    return index


def captured_gain(
    values: list[Decimal], prior_holdings_values: list[Decimal], dividends: list[Decimal]
) -> Decimal:
    """What return_index can see of the portfolio's gain, in money: every
    day's price move of the holdings (today's prices against yesterday's)
    plus the dividends credited. Set against the investment result, which
    comes from the actual cash flows, it shows how much of the gain the
    daily history misses -- an instrument without daily quotes keeps a
    constant value, so its gain never shows as a price move (#273)."""
    return sum(
        (
            prior_holdings_values[day] - values[day - 1] + dividends[day]
            for day in range(1, len(values))
        ),
        Decimal(0),
    )


def composition_changes(
    quantities: dict[str, list[Decimal]], days: list[date]
) -> list[tuple[date, str, Decimal]]:
    """(day, instrument key, change) wherever a held quantity changes --
    the jumps in the value line that are not price moves. The first day is
    the starting state, not a change."""
    changes = []
    for key, series in quantities.items():
        for index in range(1, len(days)):
            delta = series[index] - series[index - 1]
            if delta:
                changes.append((days[index], key, delta))
    return sorted(changes, key=lambda change: (change[0], change[1]))


class MissingFxRateError(Exception):
    def __init__(self, currency: str) -> None:
        super().__init__(f"No NBP rate series for {currency}")
        self.currency = currency


def base_rate_lookup(
    currency: str, fx_rates: dict[str, dict[date, Decimal]]
) -> Callable[[date], Decimal]:
    """Currency -> PLN rate on a day (last published on or before it).
    Raises MissingFxRateError when the currency has no series."""
    series = _series_or_none(currency, fx_rates)
    if series is None:
        raise MissingFxRateError(currency)
    if not series:
        return lambda _day: Decimal(1)
    return _AsOfLookup(series).at


def _series_or_none(
    currency: str, fx_rates: dict[str, dict[date, Decimal]]
) -> dict[date, Decimal] | None:
    if currency == BASE_CURRENCY:
        return {}
    rates = fx_rates.get(currency)
    return rates if rates else None


class _AsOfLookup:
    """Value on the last date on or before a day; before the first known
    date, the first known value (e.g. a price before the listing's first
    close in the fetched window) rather than nothing."""

    def __init__(self, series: dict[date, Decimal]) -> None:
        self._dates = sorted(series)
        self._values = [series[d] for d in self._dates]

    def at(self, day: date) -> Decimal:
        position = bisect_right(self._dates, day) - 1
        return self._values[max(position, 0)]

    def last_on_or_before(self, day: date) -> date | None:
        position = bisect_right(self._dates, day) - 1
        return self._dates[position] if position >= 0 else None
