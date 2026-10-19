"""Holdings history of an XTB account from its lots (fin-ai-lab#249) -- pure
computation, no database, no network.

The snapshots only know what is still held. The closed lots (when each was
opened and closed) plus the open lots of the latest snapshot say what was
held on every day since the account started, including everything bought and
sold in between. This turns them into the inputs valuation.py already takes:
signed quantity changes per instrument key, and -- for an instrument no
longer held, which has no snapshot row to anchor its price on -- an anchor
from its last sale and the Yahoo symbol to move it by.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from fin_ai_lab.portfolio_webapp.closed_lots import ClosedLot
from fin_ai_lab.portfolio_webapp.valuation import Anchor, QuantityChange
from fin_ai_lab.portfolio_webapp.xtb_symbols import (
    candidate_quote_currencies,
    yahoo_symbol,
)


def xtb_key(ticker: str) -> str:
    """The instrument key of an XTB position: aggregators.instrument_key
    gives broker:symbol to an instrument without an ISIN, which is every
    XTB instrument."""
    return f"xtb:{ticker}"


@dataclass(frozen=True)
class OpenHolding:
    """A position of the latest snapshot. `dated_lots` are its open lots
    (quantity, opened on) where they add up to the whole quantity; without
    them the position counts from `held_on`, the snapshot's date."""

    key: str
    quantity: Decimal
    dated_lots: list[tuple[Decimal, date]]
    held_on: date


@dataclass(frozen=True)
class PendingQuote:
    """A London listing can be quoted in USD, GBP or EUR; which one is read
    from the last lot once the NBP rates are in (xtb_symbols)."""

    ticker: str
    account_currency: str
    cost_ratio: float  # cost per unit in the account currency / open price
    opened_on: date


@dataclass
class LotHistory:
    changes: list[QuantityChange] = field(default_factory=list)
    anchors: dict[str, Anchor] = field(default_factory=dict)
    tickers: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    pending_quotes: dict[str, PendingQuote] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)  # instruments left out
    dates: list[date] = field(default_factory=list)


def build_lot_history(
    closed_lots: list[ClosedLot], open_holdings: list[OpenHolding], anchored_keys: set[str]
) -> LotHistory:
    """`anchored_keys` are the instruments a snapshot already prices; those
    keep their anchor and ticker. An instrument with neither an anchor nor a
    Yahoo symbol cannot be priced, so its lots are left out and named."""
    history = LotHistory()
    last_lot: dict[str, ClosedLot] = {}
    skipped: dict[str, None] = {}

    for lot in closed_lots:
        key = xtb_key(lot.ticker)
        if key not in anchored_keys and yahoo_symbol(lot.ticker) is None:
            skipped[lot.instrument] = None
            continue
        history.changes.append(QuantityChange(key, lot.opened_at.date(), lot.volume))
        history.changes.append(QuantityChange(key, lot.closed_at.date(), -lot.volume))
        history.dates.append(lot.opened_at.date())
        history.names.setdefault(key, lot.instrument)
        if key not in last_lot or lot.closed_at > last_lot[key].closed_at:
            last_lot[key] = lot

    for holding in open_holdings:
        if holding.quantity <= 0:
            continue
        for quantity, opened_on in holding.dated_lots or [(holding.quantity, holding.held_on)]:
            history.changes.append(QuantityChange(holding.key, opened_on, quantity))
            history.dates.append(opened_on)

    for key, lot in last_lot.items():
        if key in anchored_keys:
            continue
        symbol = yahoo_symbol(lot.ticker)
        if symbol is None:  # cannot happen: filtered above
            continue
        candidates = candidate_quote_currencies(lot.ticker)
        ambiguous = len(candidates) > 1 and lot.open_price > 0
        history.tickers[key] = symbol
        history.anchors[key] = Anchor(
            unit_value=lot.sale_value / lot.volume,
            currency=lot.currency,
            as_of=lot.closed_at.date(),
            quote_currency=candidates[0] if len(candidates) == 1 else None,
        )
        if ambiguous:
            history.pending_quotes[key] = PendingQuote(
                ticker=lot.ticker,
                account_currency=lot.currency,
                cost_ratio=float(lot.purchase_value / lot.volume / lot.open_price),
                opened_on=lot.opened_at.date(),
            )
    history.skipped = list(skipped)
    return history
