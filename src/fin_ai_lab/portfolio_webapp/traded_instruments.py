"""Which listing prices an instrument the Bossa ledger traded (fin-ai-lab#277)
-- pure computation, no database, no network.

Only a position still held is identified at import, so an instrument already
sold has no ticker, and a held foreign one often stays `ambiguous`: OpenFIGI
returns dozens of listings for it and the broker market (GPW) narrows none
of them. The value history needs a ticker for every instrument ever held, so
each ISIN of the ledger gets one listing here, chosen by the currency the
trade settled in -- the one fact Bossa states about where it was bought.

The value history moves a unit's value by its listing's price ratio (and FX
ratio, valuation.unit_value_series), never by an absolute price, so any
listing of the instrument quoted in a known currency is good enough; the
rules below only avoid listings Yahoo has no data for.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from fin_ai_lab.portfolio_xray.identification.openfigi import Listing
from fin_ai_lab.portfolio_xray.ledger import BossaTransaction
from fin_ai_lab.portfolio_xray.metrics.price_history import to_yahoo_ticker

# OpenFIGI exchange codes Yahoo can be asked about: to_yahoo_ticker knows the
# suffix of the LSE (LN) and the GPW (PW), and the US composite needs none.
_YAHOO_EXCHANGES = ("US", "LN", "PW")

# Seen on the owner's 128 Bossa ISINs: a PLN trade is a GPW listing; in USD a
# UCITS fund (ETP) is the LSE's USD line -- an EU investor cannot buy a fund
# in the US, and its US "listing" is an OTC line with stale prices (VUAA ->
# VGFPF) -- while a stock or ADR is the US composite.
_GPW, _LSE, _US = "PW", "LN", "US"

# A foreign instrument bought in PLN outside the GPW (Moderna, "MRNAPLN" on
# an exchange Yahoo does not know) is looked up again in this currency.
FALLBACK_CURRENCY = "USD"

ListingStatus = Literal["resolved", "unresolved"]


@dataclass(frozen=True)
class InstrumentListing:
    """The listing chosen for one ISIN, or `unresolved` without one (kept, so
    the next import does not ask OpenFIGI again)."""

    isin: str
    status: ListingStatus
    figi: str | None = None
    ticker: str | None = None
    exchange_code: str | None = None
    identification_rule: str | None = None
    quote_currency: str | None = None  # Yahoo's own currency of the listing

    @property
    def yahoo_ticker(self) -> str | None:
        if self.ticker is None:
            return None
        return to_yahoo_ticker(self.ticker, self.exchange_code)


def latest_trade_currencies(transactions: Iterable[BossaTransaction]) -> dict[str, str]:
    """ISIN -> the currency its latest trade settled in. The latest, because
    the value history anchors a sold instrument on its latest trade."""
    ordered = sorted(transactions, key=lambda t: t.executed_at)
    return {transaction.isin: transaction.currency for transaction in ordered}


def choose_listing(listings: list[Listing], currency: str) -> tuple[Listing, str] | None:
    """The listing to price an instrument traded in `currency` by, with the
    rule that chose it; None when no rule picks exactly one listing Yahoo
    knows."""
    market = _preferred_market(listings, currency)
    if market is not None:
        hits = [listing for listing in listings if listing.exchange_code == market]
        if len(hits) == 1:
            return hits[0], f"{market} listing for a {currency} trade"
    if len(listings) == 1 and listings[0].exchange_code in _YAHOO_EXCHANGES:
        return listings[0], "only listing in currency"
    return None


def _preferred_market(listings: list[Listing], currency: str) -> str | None:
    if currency == "PLN":
        return _GPW
    if currency == "USD":
        is_fund = bool(listings) and all(listing.security_type == "ETP" for listing in listings)
        return _LSE if is_fund else _US
    return None
