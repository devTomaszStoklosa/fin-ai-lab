"""Gathers everything valuation.py needs for one or more portfolios --
holdings from the database, daily closes from yfinance, NBP rate series --
and turns its results into the API's ValuationOut (portfolio-webapp-S10).
All network access goes through the injected fetcher/client, so tests run
on canned series."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Protocol
from uuid import UUID

import duckdb

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.cash_operations import CashOperation
from fin_ai_lab.portfolio_webapp.closed_lots import ClosedLot
from fin_ai_lab.portfolio_webapp.instrument_overrides import InstrumentOverride
from fin_ai_lab.portfolio_webapp.instruments import display_name
from fin_ai_lab.portfolio_webapp.instruments_builder import (
    LinkState,
    load_link_state,
    suggestions_in_scope,
)
from fin_ai_lab.portfolio_webapp.investment_result import CashFlow, investment_result
from fin_ai_lab.portfolio_webapp.lot_history import (
    OpenHolding,
    PendingQuote,
    build_lot_history,
)
from fin_ai_lab.portfolio_webapp.lots import XTB_BROKER
from fin_ai_lab.portfolio_webapp.manual_valuations import ManualValuation
from fin_ai_lab.portfolio_webapp.repository import PortfolioRow, PositionRow
from fin_ai_lab.portfolio_webapp.schemas import (
    AssetOut,
    CompositionChangeOut,
    InvestmentOut,
    PortfolioSeriesOut,
    ValuationOut,
    ValuedPositionOut,
)
from fin_ai_lab.portfolio_webapp.traded_instruments import InstrumentListing
from fin_ai_lab.portfolio_webapp.valuation import (
    BASE_CURRENCY,
    Anchor,
    Lot,
    MissingFxRateError,
    QuantityChange,
    SnapshotHoldings,
    UnitValues,
    base_rate_lookup,
    captured_gain,
    composition_changes,
    day_range,
    fx_currency_code,
    prior_holdings_value_series,
    quantities_from_changes,
    quantities_from_snapshots,
    return_index,
    unit_value_series,
    value_series,
)
from fin_ai_lab.portfolio_webapp.xtb_symbols import (
    candidate_quote_currencies,
    quote_currency_from_lot,
)
from fin_ai_lab.portfolio_webapp.yahoo_ticker import position_yahoo_ticker

# A chart, not an archive: five years of daily points is already ~1800 per
# series, and yfinance/NBP history further back adds load for no reader.
MAX_HISTORY_DAYS = 5 * 366
# Modest on purpose: yfinance is unofficial and sometimes blocks bursts
# (docs/DATA-SOURCES.md); this only overlaps a handful of lookups.
PRICE_FETCH_CONCURRENCY = 4

MONEY = Decimal("0.01")
PRICE = Decimal("0.0001")
PERCENT = Decimal("0.1")
# A return index (1 = the first day): six places keep a 0.01 pp difference
# exact after years of compounding.
INDEX = Decimal("0.000001")

# Key prefix of a manual position: the owner's own figure, never merged with
# an imported instrument.
MANUAL_PREFIX = "manual:"

# (ticker, start, refresh) -> closes by trading date, or None without data.
DailyClosesFetcher = Callable[[str, date, bool], dict[date, Decimal] | None]


class FxSeriesClient(Protocol):
    def mid_rate_series(
        self, currency: str, start: date, end: date
    ) -> Awaitable[dict[date, Decimal]]: ...


@dataclass(frozen=True)
class _CostedRow:
    """A current position whose purchase cost the import states: its key,
    its row, and what it cost (one flow per dated lot where the broker gave
    them)."""

    key: str
    row: PositionRow
    flows: list[CashFlow]


@dataclass
class _PortfolioInputs:
    row: PortfolioRow
    snapshots: list[SnapshotHoldings] = field(default_factory=list)
    # Ledger transactions (Bossa) and manual entries -- exact changes.
    changes: list[QuantityChange] = field(default_factory=list)
    is_ledger: bool = False
    anchors: dict[str, Anchor] = field(default_factory=dict)
    tickers: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    current_rows: list[tuple[str, PositionRow]] = field(default_factory=list)
    earliest: date | None = None
    # Investment result inputs. A ledger states every purchase and sale; for
    # a state-shaped export (XTB) and manual entries only the cost of what
    # is still held is known.
    purchases: list[CashFlow] = field(default_factory=list)
    sales: list[CashFlow] = field(default_factory=list)
    # XTB cash operations (#241): with them, purchases and sales are exact
    # cash flows like a ledger's, and what the account earned on the side
    # comes with them.
    has_cash_history: bool = False
    # A ledger (Bossa) with cash operations (#246): trades still come from the
    # ledger, only dividends, fees and deposits from the operations.
    has_side_cash: bool = False
    dividends: list[CashFlow] = field(default_factory=list)
    interest: list[CashFlow] = field(default_factory=list)
    other: list[CashFlow] = field(default_factory=list)
    deposits: list[CashFlow] = field(default_factory=list)  # signed: withdrawals negative
    costed_rows: list[_CostedRow] = field(default_factory=list)
    uncosted_names: list[str] = field(default_factory=list)
    # #249: an XTB account whose closed lots are stored -- the holdings
    # history comes from lots (closed and open), not from the snapshots.
    has_lot_history: bool = False
    pending_quotes: dict[str, PendingQuote] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


async def build_valuation(
    connection: duckdb.DuckDBPyConnection,
    portfolio_rows: list[PortfolioRow],
    *,
    today: date,
    refresh: bool,
    closes_fetcher: DailyClosesFetcher,
    fx_client: FxSeriesClient,
    link_state: LinkState | None = None,
) -> ValuationOut:
    """Positions come out under their asset key (S12), so one asset held
    through two brokers is one row in `assets` and one slice in a breakdown;
    the history itself is computed per portfolio on per-broker keys."""
    if link_state is None:
        link_state = load_link_state(connection)
    listings = repository.list_instrument_listings(connection)
    overrides = repository.list_instrument_overrides(connection)
    inputs = [_collect_inputs(connection, row, listings, overrides) for row in portfolio_rows]
    computed_at = datetime.now(UTC)

    earliest = min((i.earliest for i in inputs if i.earliest is not None), default=None)
    if earliest is None:
        return ValuationOut(
            base_currency=BASE_CURRENCY,
            computed_at=computed_at,
            prices_as_of=None,
            total_value=Decimal(0),
            dates=[],
            totals=[],
            portfolios=[_empty_series(i) for i in inputs],
            positions=[],
            changes=[],
            warnings=[],
        )

    start = max(min(earliest, today), today - timedelta(days=MAX_HISTORY_DAYS))
    days = day_range(start, today)

    anchors = [anchor for i in inputs for anchor in i.anchors.values()]
    # First of the month, so the single-portfolio and all-portfolio views
    # (different earliest dates) mostly ask yfinance for the same window
    # and share its daily cache entry.
    fetch_start = min([start, *(a.as_of for a in anchors)]) - timedelta(days=10)
    fetch_start = fetch_start.replace(day=1)

    tickers = sorted(
        {
            ticker
            for i in inputs
            for key, ticker in i.tickers.items()
            if key in i.anchors and i.anchors[key].moves_with_market
        }
    )
    closes_by_ticker = await _fetch_closes(tickers, fetch_start, refresh, closes_fetcher)
    currencies = {a.currency for a in anchors} | {
        fx_currency_code(a.quote_currency) for a in anchors if a.quote_currency
    }
    # Purchases and sales are converted on their own day, which can lie
    # before the (capped) chart window.
    flows = [flow for i in inputs for flow in _all_flows(i)]
    currencies |= {flow.currency for flow in flows}
    pending = [p for i in inputs for p in i.pending_quotes.values()]
    for quote in pending:
        currencies |= {quote.account_currency, *candidate_quote_currencies(quote.ticker)}
    fx_start = min(
        [
            fetch_start,
            *(flow.on - timedelta(days=10) for flow in flows),
            *(quote.opened_on - timedelta(days=10) for quote in pending),
        ]
    )
    fx_start = fx_start.replace(day=1)
    fx_rates = await _fetch_fx(fx_client, currencies - {BASE_CURRENCY}, fx_start, today)
    for portfolio in inputs:
        _resolve_quote_currencies(portfolio, fx_rates)

    warnings: list[str] = [note for i in inputs for note in i.notes]
    series_out: list[PortfolioSeriesOut] = []
    positions_out: list[ValuedPositionOut] = []
    changes_out: list[CompositionChangeOut] = []
    price_dates: list[date] = []
    totals = [Decimal(0)] * len(days)
    prior_totals = [Decimal(0)] * len(days)
    dividend_totals = [Decimal(0)] * len(days)

    for portfolio in inputs:
        portfolio_id = portfolio.row[0]
        quantities = _quantities(portfolio, days)

        units: dict[str, UnitValues] = {}
        for key in quantities:
            if not any(quantities[key]):
                continue
            unit = _unit_values(portfolio, key, days, closes_by_ticker, fx_rates, warnings)
            if unit is not None:
                units[key] = unit
                if unit.last_price_date is not None:
                    price_dates.append(unit.last_price_date)

        unit_bases = {key: unit.base for key, unit in units.items()}
        values = value_series(quantities, unit_bases, len(days))
        prior = prior_holdings_value_series(quantities, unit_bases, len(days))
        dividends, _ = _flows_by_day(portfolio, portfolio.dividends, days, fx_rates, warnings)
        deposits, deposits_before = _flows_by_day(
            portfolio, portfolio.deposits, days, fx_rates, warnings
        )
        # Held without daily quotes: a constant value, so no return (#273).
        unquoted = value_series(
            quantities,
            {key: unit.base for key, unit in units.items() if unit.last_price_date is None},
            len(days),
        )
        totals = [total + value for total, value in zip(totals, values, strict=True)]
        prior_totals = [total + value for total, value in zip(prior_totals, prior, strict=True)]
        dividend_totals = [
            total + value for total, value in zip(dividend_totals, dividends, strict=True)
        ]

        portfolio_positions = [
            _valued_position(
                portfolio_id,
                link_state.identities.asset_key(key),
                row,
                units.get(key),
                portfolio.anchors.get(key),
                portfolio.tickers.get(key),
                overrides.get(key),
            )
            for key, row in portfolio.current_rows
        ]
        positions_out.extend(portfolio_positions)
        series_out.append(
            PortfolioSeriesOut(
                id=portfolio_id,
                name=portfolio.row[1],
                broker=portfolio.row[2],
                account_type=portfolio.row[3],
                current_value=_money(values[-1]),
                position_count=len(portfolio.current_rows),
                values=[_money(v) for v in values],
                investment=_investment(portfolio, quantities, units, fx_rates, warnings),
                prior_holdings_values=[_money(v) for v in prior],
                dividends_by_day={
                    day: _money(amount)
                    for day, amount in zip(days, dividends, strict=True)
                    if amount
                },
                dividends_included="dividends" not in _not_covered(portfolio),
                unquoted_values=[_money(v) for v in unquoted],
                history_gain=_money(captured_gain(values, prior, dividends)),
                deposits_by_day={
                    day: _money(amount)
                    for day, amount in zip(days, deposits, strict=True)
                    if amount
                },
                deposits_before_start=_money(deposits_before),
            )
        )
        changes_out.extend(
            CompositionChangeOut(
                date=day,
                portfolio_id=portfolio_id,
                instrument_name=portfolio.names.get(key, key),
                quantity_change=delta,
            )
            for day, key, delta in composition_changes(quantities, days)
        )

    positions_out.sort(key=lambda p: p.value if p.value is not None else Decimal(-1), reverse=True)
    return ValuationOut(
        base_currency=BASE_CURRENCY,
        computed_at=computed_at,
        prices_as_of=max(price_dates, default=None),
        total_value=_money(totals[-1]),
        dates=days,
        totals=[_money(t) for t in totals],
        portfolios=series_out,
        positions=positions_out,
        assets=assets_from_positions(positions_out),
        changes=sorted(changes_out, key=lambda c: c.date),
        warnings=list(dict.fromkeys(warnings)),
        link_suggestion_count=len(suggestions_in_scope(link_state, positions_out)),
        return_index=[
            value.quantize(INDEX, rounding=ROUND_HALF_UP)
            for value in return_index(totals, prior_totals, dividend_totals)
        ],
    )


def assets_from_positions(positions: list[ValuedPositionOut]) -> list[AssetOut]:
    """One row per asset key, most valuable first (REQ-093)."""
    by_asset: dict[str, list[ValuedPositionOut]] = {}
    for position in positions:
        by_asset.setdefault(position.instrument_key, []).append(position)
    assets = [_asset(key, members) for key, members in by_asset.items()]
    assets.sort(key=lambda a: a.value if a.value is not None else Decimal(-1), reverse=True)
    return assets


def _asset(key: str, members: list[ValuedPositionOut]) -> AssetOut:
    # The member keyed by the asset's own ISIN leads: its identifiers are
    # the broker-independent ones.
    members = sorted(members, key=lambda p: p.isin != key)
    quantity = sum((p.quantity for p in members), Decimal(0))
    values = [p.value for p in members if p.value is not None]
    classes = [p.asset_class for p in members if p.asset_class != "other"]
    base = dict(
        instrument_key=key,
        instrument_name=display_name([p.instrument_name for p in members]),
        isin=next((p.isin for p in members if p.isin), None),
        symbol=next((p.symbol for p in members if p.symbol), None),
        # Bossa's ledger has no instrument type ("other") -- a joined
        # broker's own category says more.
        asset_class=classes[0] if classes else "other",
        quantity=quantity,
        quote_currency=next((p.quote_currency for p in members if p.quote_currency), None),
        value=_money(sum(values, Decimal(0))) if values else None,
        position_ids=[p.position_id for p in members],
    )
    if len(members) == 1:
        (only,) = members
        return AssetOut(
            **base,
            avg_cost=only.avg_cost,
            cost_currency=only.cost_currency,
            current_price=only.current_price,
            price_currency=only.price_currency,
            return_pct=only.return_pct,
        )

    avg_cost, cost_currency = _weighted(members, lambda p: (p.avg_cost, p.cost_currency))
    price, price_currency = _weighted(members, lambda p: (p.current_price, p.price_currency))
    return_pct = None
    if avg_cost and price is not None and cost_currency == price_currency and quantity > 0:
        return_pct = ((price / avg_cost - 1) * 100).quantize(PERCENT, ROUND_HALF_UP)
    return AssetOut(
        **base,
        avg_cost=avg_cost,
        cost_currency=cost_currency,
        current_price=price,
        price_currency=price_currency,
        return_pct=return_pct,
    )


def _weighted(
    members: list[ValuedPositionOut],
    field_of: Callable[[ValuedPositionOut], tuple[Decimal | None, str | None]],
) -> tuple[Decimal | None, str | None]:
    """Quantity-weighted average of a per-unit figure -- only when every
    member states it, in one and the same currency."""
    figures = [field_of(p) for p in members]
    currencies = {currency for _, currency in figures}
    if any(amount is None for amount, _ in figures) or len(currencies) != 1 or None in currencies:
        return None, None
    quantity = sum((p.quantity for p in members), Decimal(0))
    if quantity <= 0:
        return None, None
    total = sum((p.quantity * amount for p, (amount, _) in zip(members, figures, strict=True)))
    return (Decimal(total) / quantity).quantize(PRICE, ROUND_HALF_UP), currencies.pop()


def _collect_inputs(
    connection: duckdb.DuckDBPyConnection,
    row: PortfolioRow,
    listings: dict[str, InstrumentListing],
    overrides: dict[str, InstrumentOverride],
) -> _PortfolioInputs:
    portfolio_id = row[0]
    inputs = _PortfolioInputs(row=row)
    earliest_dates: list[date] = []

    # Oldest first: of two imports on the same valuation date, the later
    # one wins, same "latest import is the truth" rule as the rest of the app.
    snapshot_rows = sorted(
        repository.list_snapshots(connection, portfolio_id), key=lambda r: (r[3], r[4])
    )
    positions_by_snapshot = {
        s[0]: repository.list_positions(connection, s[0]) for s in snapshot_rows
    }
    lots_by_position = repository.list_lots(
        connection, [p[0] for rows in positions_by_snapshot.values() for p in rows]
    )

    holdings_by_date: dict[date, SnapshotHoldings] = {}
    for snapshot_row in snapshot_rows:
        quantities: dict[str, Decimal] = {}
        lots: dict[str, list[Lot]] = {}
        for position_row in positions_by_snapshot[snapshot_row[0]]:
            key = _key(position_row)
            quantities[key] = quantities.get(key, Decimal(0)) + position_row[8]
            for quantity, opened_on in lots_by_position.get(position_row[0], []):
                lots.setdefault(key, []).append(Lot(quantity, opened_on))
        # Lots only count where they account for the whole quantity (the
        # import already checks this per position; this guards a key two
        # positions share).
        lots = {
            key: key_lots
            for key, key_lots in lots.items()
            if sum((lot.quantity for lot in key_lots), Decimal(0)) == quantities[key]
        }
        holdings_by_date[snapshot_row[3]] = SnapshotHoldings(snapshot_row[3], quantities, lots)
        earliest_dates.append(snapshot_row[3])
        earliest_dates.extend(lot.opened_on for key_lots in lots.values() for lot in key_lots)
    inputs.snapshots = list(holdings_by_date.values())

    # Newest first: the most recent import holding an instrument anchors
    # its value, names it and says where to look up its price.
    for snapshot_row in reversed(snapshot_rows):
        for position_row in positions_by_snapshot[snapshot_row[0]]:
            key = _key(position_row)
            inputs.names.setdefault(key, position_row[4])
            ticker = _yahoo_ticker(position_row)
            if ticker is not None:
                inputs.tickers.setdefault(key, ticker)
            anchor = _anchor_from_position(position_row)
            if anchor is not None:
                inputs.anchors.setdefault(key, anchor)

    transactions = repository.list_transactions(connection, portfolio_id)
    if transactions:
        # A ledger (Bossa) states every change on its own day: exact, so it
        # replaces the step-between-imports reading of its snapshots.
        inputs.is_ledger = True
        for transaction in transactions:
            sign = Decimal(1) if transaction.side == "buy" else Decimal(-1)
            inputs.changes.append(
                QuantityChange(
                    transaction.isin, transaction.executed_at.date(), sign * transaction.quantity
                )
            )
            inputs.names.setdefault(transaction.isin, transaction.instrument_name)
            earliest_dates.append(transaction.executed_at.date())
            # net_value is after commission: what the purchase cost, what
            # the sale paid out.
            flow = CashFlow(
                transaction.executed_at.date(), transaction.currency, abs(transaction.net_value)
            )
            (inputs.purchases if transaction.side == "buy" else inputs.sales).append(flow)
        # An instrument bought and sold between two imports was never in a
        # snapshot, so nothing valued it -- its own latest trade price is
        # then the only known value of one unit, on that trade's day.
        latest_trades = {t.isin: t for t in sorted(transactions, key=lambda t: t.executed_at)}
        for key, trade in latest_trades.items():
            if key not in inputs.anchors:
                inputs.anchors[key] = Anchor(
                    unit_value=trade.price, currency=trade.currency, as_of=trade.executed_at.date()
                )
            _add_listing(inputs, key, listings.get(key))

    latest_rows = positions_by_snapshot[snapshot_rows[-1][0]] if snapshot_rows else []
    inputs.current_rows = [(_key(r), r) for r in latest_rows]
    cash_operations = repository.list_cash_operations(connection, portfolio_id)
    if cash_operations and inputs.is_ledger:
        inputs.has_side_cash = True
        _add_cash_flows(inputs, cash_operations, trades=False)
    elif cash_operations:
        inputs.has_cash_history = True
        _add_cash_flows(inputs, cash_operations, trades=True)
    elif not inputs.is_ledger and snapshot_rows:
        # Neither a ledger (its snapshot is only a replay of the transactions
        # above) nor cash operations state what was paid, so the cost of
        # what is still held comes from the snapshot's average cost.
        held_on = snapshot_rows[-1][3]
        for position_row in latest_rows:
            _add_costed_row(inputs, _key(position_row), position_row, lots_by_position, held_on)

    closed_lots = (
        [] if inputs.is_ledger else repository.list_closed_lots(connection, portfolio_id)
    )
    if closed_lots and snapshot_rows:
        held_on = snapshot_rows[-1][3]
        _add_lot_history(
            inputs, closed_lots, latest_rows, lots_by_position, held_on, earliest_dates
        )
    _apply_overrides(inputs, overrides)

    manual_snapshot = repository.find_manual_snapshot(connection, portfolio_id)
    if manual_snapshot is not None:
        for position_row in repository.list_positions(connection, manual_snapshot[0]):
            # Own key per row: a manual entry is the owner's own figure and
            # must never merge with (or re-price) an imported instrument.
            key = f"{MANUAL_PREFIX}{position_row[0]}"
            inputs.current_rows.append((key, position_row))
            _add_costed_row(inputs, key, position_row, {}, position_row[13])
            inputs.changes.append(QuantityChange(key, position_row[13], position_row[8]))
            inputs.names[key] = position_row[4]
            earliest_dates.append(position_row[13])
            valuations = repository.list_manual_valuations(connection, position_row[0])
            anchor = _manual_anchor(position_row, valuations)
            if anchor is not None:
                inputs.anchors[key] = anchor

    inputs.earliest = min(earliest_dates, default=None)
    return inputs


def _add_listing(inputs: _PortfolioInputs, key: str, listing: InstrumentListing | None) -> None:
    """A traded ISIN without a ticker of its own -- sold, or held but left
    ambiguous at import -- is priced by the listing stored for it (#277),
    in that listing's quote currency where the anchor states none. A
    position's own ticker always wins."""
    if key in inputs.tickers or listing is None or listing.yahoo_ticker is None:
        return
    inputs.tickers[key] = listing.yahoo_ticker
    anchor = inputs.anchors[key]
    if anchor.quote_currency is None and listing.quote_currency is not None:
        inputs.anchors[key] = replace(anchor, quote_currency=listing.quote_currency)


def _apply_overrides(inputs: _PortfolioInputs, overrides: dict[str, InstrumentOverride]) -> None:
    """The owner's own Yahoo symbol and quote currency (#285) win over
    everything the imports found -- a position's ticker, a stored listing, a
    currency read from a lot -- since the owner entered them where those
    found nothing or the wrong listing. Called before manual entries are
    added: those have their own keys and are never re-priced."""
    for key, override in overrides.items():
        anchor = inputs.anchors.get(key)
        if anchor is None:
            continue
        if override.yahoo_ticker is not None:
            inputs.tickers[key] = override.yahoo_ticker
        if override.quote_currency is not None:
            inputs.anchors[key] = replace(anchor, quote_currency=override.quote_currency)
            inputs.pending_quotes.pop(key, None)


def _add_lot_history(
    inputs: _PortfolioInputs,
    closed_lots: list[ClosedLot],
    latest_rows: list[PositionRow],
    lots_by_position: dict[UUID, list[tuple[Decimal, date]]],
    held_on: date,
    earliest_dates: list[date],
) -> None:
    """Quantities from lots instead of the snapshots (#249): every closed lot
    from its open to its close day, every open lot of the latest snapshot
    from its open day. Instruments no snapshot prices get an anchor from
    their last sale."""
    holdings = []
    for row in latest_rows:
        lots = lots_by_position.get(row[0], [])
        complete = sum((quantity for quantity, _ in lots), Decimal(0)) == row[8]
        holdings.append(
            OpenHolding(
                key=_key(row),
                quantity=row[8],
                dated_lots=lots if complete else [],
                held_on=held_on,
            )
        )
    history = build_lot_history(closed_lots, holdings, set(inputs.anchors))
    inputs.has_lot_history = True
    inputs.changes.extend(history.changes)
    inputs.anchors.update(history.anchors)
    inputs.tickers.update(history.tickers)
    for key, name in history.names.items():
        inputs.names.setdefault(key, name)
    inputs.pending_quotes.update(history.pending_quotes)
    earliest_dates.extend(history.dates)
    if history.skipped:
        shown = ", ".join(history.skipped[:5]) + (" …" if len(history.skipped) > 5 else "")
        inputs.notes.append(
            f"{len(history.skipped)} instrumentów bez symbolu notowań (CFD, krypto, nieznana "
            f"giełda) pominiętych w historii wartości: {shown}."
        )


def _add_costed_row(
    inputs: _PortfolioInputs,
    key: str,
    row: PositionRow,
    lots_by_position: dict[UUID, list[tuple[Decimal, date]]],
    held_on: date,
) -> None:
    """Records what a held position cost. The broker's average cost is spread
    over the dated lots when they account for the whole quantity, so each
    lot is converted at its own purchase day; otherwise the whole cost is
    dated `held_on` (the import), which only misses the currency move since
    the real purchase."""
    quantity, avg_cost, currency = row[8], row[9], row[10]
    if quantity <= 0:
        return
    if avg_cost is None or currency is None:
        inputs.uncosted_names.append(row[4])
        return
    lots = lots_by_position.get(row[0], [])
    if lots and sum((lot_quantity for lot_quantity, _ in lots), Decimal(0)) == quantity:
        flows = [
            CashFlow(opened_on, currency, lot_quantity * avg_cost)
            for lot_quantity, opened_on in lots
        ]
    else:
        flows = [CashFlow(held_on, currency, quantity * avg_cost)]
    inputs.costed_rows.append(_CostedRow(key, row, flows))


def _add_cash_flows(
    inputs: _PortfolioInputs, operations: list[CashOperation], *, trades: bool
) -> None:
    """XTB reports a purchase as a negative amount and a sale as a positive
    one; the flows hold the cost and the proceeds. Dividends, interest and
    fees stay signed. With `trades` False the purchases and sales are left
    out: a ledger already states them."""
    for operation in operations:
        if not trades and operation.kind in ("purchase", "sale"):
            continue
        day = operation.occurred_at.date()
        flow = CashFlow(day, operation.currency, operation.amount)
        if operation.kind == "purchase":
            inputs.purchases.append(CashFlow(day, operation.currency, -operation.amount))
        elif operation.kind == "sale":
            inputs.sales.append(flow)
        elif operation.kind == "dividend":
            inputs.dividends.append(flow)
        elif operation.kind == "interest":
            inputs.interest.append(flow)
        elif operation.kind == "transfer":
            inputs.deposits.append(flow)
        else:
            inputs.other.append(flow)


def _resolve_quote_currencies(
    portfolio: _PortfolioInputs, fx_rates: dict[str, dict[date, Decimal]]
) -> None:
    """Fills in the quote currency of the London listings whose currency is
    read from their last lot (xtb_symbols.quote_currency_from_lot). Without a
    rate for a candidate, that candidate is simply not considered."""
    for key, pending in portfolio.pending_quotes.items():
        rates: dict[str, float] = {}
        try:
            account_rate = base_rate_lookup(pending.account_currency, fx_rates)(pending.opened_on)
        except MissingFxRateError:
            continue
        for currency in candidate_quote_currencies(pending.ticker):
            try:
                rate = base_rate_lookup(currency, fx_rates)(pending.opened_on)
            except MissingFxRateError:
                continue
            rates[currency] = float(rate / account_rate)
        quote = quote_currency_from_lot(
            pending.ticker, pending.account_currency, pending.cost_ratio, rates
        )
        if quote is not None:
            portfolio.anchors[key] = replace(portfolio.anchors[key], quote_currency=quote)


def _flows_by_day(
    portfolio: _PortfolioInputs,
    flows: list[CashFlow],
    days: list[date],
    fx_rates: dict[str, dict[date, Decimal]],
    warnings: list[str],
) -> tuple[list[Decimal], Decimal]:
    """Cash flows (dividends, deposits) summed per chart day, in PLN at the
    NBP rate of their own day (#273), as the cash operations state them --
    a dividend net of withholding tax, a withdrawal negative. Flows before
    the chart's first day come back as one sum; a flow in a currency without
    an NBP series is left out with a warning."""
    series = [Decimal(0)] * len(days)
    before = Decimal(0)
    for flow in flows:
        position = (flow.on - days[0]).days
        if position >= len(days):
            continue
        try:
            rate = base_rate_lookup(flow.currency, fx_rates)(flow.on)
        except MissingFxRateError:
            warnings.append(
                f"{portfolio.row[1]}: operacja z {flow.on.isoformat()} pominięta w porównaniu "
                f"z benchmarkiem — brak kursu NBP dla {flow.currency}."
            )
            continue
        if position < 0:
            before += flow.amount * rate
        else:
            series[position] += flow.amount * rate
    return series, before


def _all_flows(portfolio: _PortfolioInputs) -> list[CashFlow]:
    return [
        *portfolio.purchases,
        *portfolio.sales,
        *portfolio.dividends,
        *portfolio.interest,
        *portfolio.other,
        *portfolio.deposits,
        *(flow for costed in portfolio.costed_rows for flow in costed.flows),
    ]


def _investment(
    portfolio: _PortfolioInputs,
    quantities: dict[str, list[Decimal]],
    units: dict[str, UnitValues],
    fx_rates: dict[str, dict[date, Decimal]],
    warnings: list[str],
) -> InvestmentOut | None:
    """None when the result cannot be stated honestly: nothing was bought
    that we know the cost of, or a rate/price needed for it is missing."""
    name = portfolio.row[1]
    purchases = list(portfolio.purchases)
    open_value = Decimal(0)

    if portfolio.is_ledger or portfolio.has_cash_history:
        for key, series in quantities.items():
            if key.startswith(MANUAL_PREFIX) or not series[-1]:
                continue
            unit = units.get(key)
            if unit is None:
                # A held instrument without a value would read as a loss.
                instrument = portfolio.names.get(key, key)
                warnings.append(f"{name}: wynik inwestycji pominięty — brak wyceny {instrument}.")
                return None
            open_value += series[-1] * unit.base[-1]

    for costed in portfolio.costed_rows:
        unit = units.get(costed.key)
        if unit is None:
            warnings.append(f"{costed.row[4]}: brak wyceny — pominięte w wyniku inwestycji.")
            continue
        purchases.extend(costed.flows)
        open_value += costed.row[8] * unit.base[-1]
    for uncosted in portfolio.uncosted_names:
        warnings.append(f"{uncosted}: brak kosztu zakupu — pominięte w wyniku inwestycji.")

    if not purchases:
        return None
    try:
        outcome = investment_result(
            purchases,
            portfolio.sales,
            open_value,
            fx_rates,
            dividends=portfolio.dividends,
            interest=portfolio.interest,
            other=portfolio.other,
            deposits=portfolio.deposits,
        )
    except MissingFxRateError as exc:
        warnings.append(f"{name}: wynik inwestycji pominięty — brak kursu NBP dla {exc.currency}.")
        return None
    return InvestmentOut(
        invested=_money(outcome.invested),
        proceeds=_money(outcome.proceeds),
        open_value=_money(outcome.open_value),
        dividends=_money(outcome.dividends),
        interest=_money(outcome.interest),
        other=_money(outcome.other),
        net_deposits=_money(outcome.net_deposits) if outcome.net_deposits is not None else None,
        result=_money(outcome.result),
        not_covered=_not_covered(portfolio),
    )


def _not_covered(portfolio: _PortfolioInputs) -> list[Literal["closed_positions", "dividends"]]:
    """What the imports do not carry: XTB cash operations state every trade
    and dividend; a Bossa ledger has every trade, and dividends once a
    financial history is imported; a plain position snapshot has neither
    closed positions nor dividends."""
    if portfolio.has_cash_history:
        return []
    if portfolio.is_ledger:
        return [] if portfolio.has_side_cash else ["dividends"]
    return ["closed_positions", "dividends"]


def _quantities(portfolio: _PortfolioInputs, days: list[date]) -> dict[str, list[Decimal]]:
    quantities = quantities_from_changes(portfolio.changes, days)
    if not (portfolio.is_ledger or portfolio.has_lot_history):
        quantities.update(quantities_from_snapshots(portfolio.snapshots, days))
    return quantities


def _unit_values(
    portfolio: _PortfolioInputs,
    key: str,
    days: list[date],
    closes_by_ticker: dict[str, dict[date, Decimal] | None],
    fx_rates: dict[str, dict[date, Decimal]],
    warnings: list[str],
) -> UnitValues | None:
    name = portfolio.names.get(key, key)
    anchor = portfolio.anchors.get(key)
    if anchor is None:
        warnings.append(f"{name}: brak żadnej wyceny — pominięte w wartości portfela.")
        return None

    ticker = portfolio.tickers.get(key)
    closes = closes_by_ticker.get(ticker) if ticker is not None else None
    if anchor.moves_with_market and not closes:
        warnings.append(
            f"{name}: brak notowań dziennych — wartość stała, z ostatniej znanej wyceny."
        )
    try:
        unit = unit_value_series(anchor, days, closes, fx_rates)
    except MissingFxRateError as exc:
        warnings.append(f"{name}: brak kursu NBP dla {exc.currency} — pominięte w wartości.")
        return None
    if unit.missing_quote_fx is not None:
        warnings.append(
            f"{name}: brak kursu NBP dla {unit.missing_quote_fx} — wykres pomija zmianę kursu "
            "tej waluty."
        )
    return unit


def _valued_position(
    portfolio_id: UUID,
    key: str,
    row: PositionRow,
    unit: UnitValues | None,
    anchor: Anchor | None,
    ticker: str | None,
    override: InstrumentOverride | None,
) -> ValuedPositionOut:
    quantity: Decimal = row[8]
    avg_cost: Decimal | None = row[9]
    cost_currency: str | None = row[10]
    # UnitValues.native is per unit in its anchor's currency -- the one the
    # broker recorded the value in, and (XTB, #189) the one avg_cost is in.
    current_price = unit.native[-1] if unit is not None else None
    price_currency = anchor.currency if unit is not None and anchor is not None else None
    return_pct = None
    if (
        current_price is not None
        and avg_cost
        and quantity > 0
        and cost_currency is not None
        and cost_currency == price_currency
    ):
        return_pct = ((current_price / avg_cost - 1) * 100).quantize(PERCENT, ROUND_HALF_UP)
    return ValuedPositionOut(
        portfolio_id=portfolio_id,
        position_id=row[0],
        instrument_key=key,
        instrument_name=row[4],
        isin=row[5],
        symbol=row[6],
        broker=row[2],
        asset_class=row[7],
        quantity=quantity,
        avg_cost=avg_cost,
        cost_currency=cost_currency,
        current_price=current_price.quantize(PRICE, ROUND_HALF_UP) if current_price else None,
        price_currency=price_currency,
        quote_currency=(
            override.quote_currency
            if override is not None and override.quote_currency is not None
            else row[19]
        ),
        price_date=unit.last_price_date if unit is not None else None,
        value=_money(quantity * unit.base[-1]) if unit is not None else None,
        return_pct=return_pct,
        is_manual=row[2] == repository.MANUAL_BROKER,
        yahoo_ticker=ticker,
        valued_quote_currency=anchor.quote_currency if anchor is not None else None,
        valued_on=(
            max((day for day, _ in anchor.revaluations), default=None)
            if anchor is not None
            else None
        ),
    )


def _anchor_from_position(row: PositionRow, *, moves_with_market: bool = True) -> Anchor | None:
    quantity, market_value, market_currency = row[8], row[11], row[12]
    if market_value is None or market_currency is None or quantity <= 0:
        return None
    return Anchor(
        unit_value=market_value / quantity,
        currency=market_currency,
        as_of=row[13],
        quote_currency=_quote_currency(row),
        moves_with_market=moves_with_market,
    )


def _manual_anchor(row: PositionRow, valuations: list[ManualValuation]) -> Anchor | None:
    """A manual position (#288): its purchase price from its purchase date
    (the row's valuation_date), then each of the owner's valuations from its
    own day on -- never moved by market data. The stored market_value
    already follows the latest valuation, so it can't be the start."""
    anchor = _anchor_from_position(row, moves_with_market=False)
    if anchor is None:
        return None
    avg_cost = row[9]
    return replace(
        anchor,
        unit_value=avg_cost if avg_cost is not None else anchor.unit_value,
        revaluations=tuple((v.valued_on, v.unit_value) for v in valuations),
    )


def _quote_currency(row: PositionRow) -> str | None:
    # The import only asks Yahoo for the quote currency of a position
    # OpenFIGI resolved. An XTB symbol's suffix still names it where only
    # one is possible (".US" -> USD, #250); London stays unknown.
    quote_currency, broker, symbol = row[19], row[2], row[6]
    if quote_currency is not None or broker != XTB_BROKER or symbol is None:
        return quote_currency
    candidates = candidate_quote_currencies(symbol)
    return candidates[0] if len(candidates) == 1 else None


def _key(row: PositionRow) -> str:
    return repository.position_key(row)


def _yahoo_ticker(row: PositionRow) -> str | None:
    return position_yahoo_ticker(
        broker=row[2], symbol=row[6], ticker=row[16], exchange_code=row[17]
    )


async def _fetch_closes(
    tickers: list[str], start: date, refresh: bool, fetcher: DailyClosesFetcher
) -> dict[str, dict[date, Decimal] | None]:
    semaphore = asyncio.Semaphore(PRICE_FETCH_CONCURRENCY)

    async def one(ticker: str) -> tuple[str, dict[date, Decimal] | None]:
        async with semaphore:
            try:
                return ticker, await asyncio.to_thread(fetcher, ticker, start, refresh)
            except Exception:
                # yfinance is unofficial and sometimes blocked
                # (docs/DATA-SOURCES.md) -- one failed ticker must degrade
                # to "no daily quotes" for that instrument, not a 500.
                return ticker, None

    return dict(await asyncio.gather(*(one(ticker) for ticker in tickers)))


async def _fetch_fx(
    fx_client: FxSeriesClient, currencies: set[str], start: date, end: date
) -> dict[str, dict[date, Decimal]]:
    rates: dict[str, dict[date, Decimal]] = {}
    for currency in sorted(currencies):
        try:
            rates[currency] = await fx_client.mid_rate_series(currency, start, end)
        except Exception:
            # Reported per instrument by _unit_values (missing series), with
            # the instrument's name -- more useful than one generic line here.
            continue
    return rates


def _empty_series(portfolio: _PortfolioInputs) -> PortfolioSeriesOut:
    return PortfolioSeriesOut(
        id=portfolio.row[0],
        name=portfolio.row[1],
        broker=portfolio.row[2],
        account_type=portfolio.row[3],
        current_value=Decimal(0),
        position_count=len(portfolio.current_rows),
        values=[],
    )


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)
