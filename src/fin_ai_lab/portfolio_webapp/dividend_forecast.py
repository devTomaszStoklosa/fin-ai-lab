"""Dividend estimate for the next calendar year (fin-ai-lab#266) -- pure
computation, no database, no network.

Method, "the last 12 months again": every per-share dividend an instrument
held today paid in the last 365 days (Yahoo, by ex-date) is assumed to
repeat in the same month of the next calendar year, times today's quantity,
at today's NBP rate. 365 days cover each calendar month once, so every month
of the target year gets the latest payout seen for it. Each holding also
carries its tax (#267, dividend_tax.py): the gross months become what
reaches the account, and what is still due in the tax return is summed
apart, never subtracted.

Where Yahoo does not know the instrument, the per-share amounts XTB stated
for the account's own payments ("0.91/ SHR") stand in. Where both exist and
their average payout differs by more than MISMATCH_TOLERANCE, the row is
flagged: the usual cause is a currency or unit mix-up (#188). Averages, not
sums, because Yahoo dates a payout by its ex-date and XTB by its payment
day, so one of them can hold one payout more inside the same window.

This is a description of what the last year's payouts would give again,
not a forecast or a recommendation.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from fin_ai_lab.portfolio_webapp.dividend_tax import UNKNOWN_TAX, DividendTax, TaxBasis

LAST_12_MONTHS = timedelta(days=365)
MONTHS_IN_YEAR = 12
MISMATCH_TOLERANCE = Decimal("0.25")
# Yahoo quotes some London listings in pence; dividends come in the same
# unit as the closes. Only the units seen in real data are mapped.
_MINOR_UNITS = {"GBp": ("GBP", Decimal(100)), "GBX": ("GBP", Decimal(100))}

Source = Literal["yahoo", "history", "none"]


@dataclass(frozen=True)
class PerShareDividend:
    on: date  # ex-date (Yahoo) or payment day (the broker's own statement)
    amount: Decimal  # per share, in `currency`
    currency: str  # ISO 4217


@dataclass(frozen=True)
class YahooListing:
    """What Yahoo says about one ticker. `latest_close` None means Yahoo has
    no prices for it -- then an empty dividend list says nothing either."""

    dividends: list[tuple[date, Decimal]]  # per share, in the quote unit
    quote_currency: str | None  # "USD", "GBp"
    latest_close: Decimal | None  # in the quote unit


@dataclass(frozen=True)
class Holding:
    key: str  # the asset key (S12)
    name: str
    quantity: Decimal
    listing: YahooListing | None  # None: no Yahoo ticker for the instrument
    own: list[PerShareDividend] = field(default_factory=list)
    tax: DividendTax = UNKNOWN_TAX  # by this holding's account and issuer


@dataclass(frozen=True)
class Estimate:
    key: str
    name: str
    quantity: Decimal
    source: Source
    per_share: Decimal | None  # paid per share over the last 12 months
    currency: str | None  # of per_share
    months: list[Decimal]  # target year, base currency, January first
    yield_fraction: Decimal | None  # per_share / latest close (Yahoo only)
    mismatch: bool
    missing_currency: str | None = None  # no NBP rate: left out of the sums
    # #267: `months` after the tax withheld before payout -- the gross amount
    # itself where the rate is unknown.
    credited_months: list[Decimal] = field(default_factory=lambda: [Decimal(0)] * MONTHS_IN_YEAR)
    top_up: Decimal = Decimal(0)  # still due in the tax return, base currency
    withheld: Decimal | None = None  # the rate; None: unknown or differing
    tax_basis: TaxBasis | Literal["mixed"] = "unknown"

    @property
    def total(self) -> Decimal:
        return sum(self.months, Decimal(0))

    @property
    def credited(self) -> Decimal:
        return sum(self.credited_months, Decimal(0))


def estimate(holding: Holding, *, today: date, rates: dict[str, Decimal]) -> Estimate:
    """`rates` maps a currency to today's rate in the base currency (the base
    currency itself to 1)."""
    since = today - LAST_12_MONTHS
    own = [d for d in holding.own if since < d.on <= today]
    yahoo = _yahoo_dividends(holding.listing, since, today)

    if yahoo is not None:
        source: Source = "yahoo"
        payouts = yahoo
    elif own:
        source, payouts = "history", own
    else:
        source, payouts = "none", []

    months = [Decimal(0)] * MONTHS_IN_YEAR
    missing = next((d.currency for d in payouts if d.currency not in rates), None)
    if missing is None:
        for payout in payouts:
            months[payout.on.month - 1] += payout.amount * holding.quantity * rates[payout.currency]

    tax = holding.tax
    kept = 1 - tax.withheld if tax.withheld is not None else Decimal(1)
    currencies = {d.currency for d in payouts}
    per_share = sum((d.amount for d in payouts), Decimal(0)) if len(currencies) == 1 else None
    return Estimate(
        key=holding.key,
        name=holding.name,
        quantity=holding.quantity,
        source=source,
        per_share=per_share if payouts else None,
        currency=currencies.pop() if len(currencies) == 1 else None,
        months=months,
        yield_fraction=_yield(holding.listing, since, today) if source == "yahoo" else None,
        mismatch=source == "yahoo" and _differ(yahoo or [], own, rates),
        missing_currency=missing,
        credited_months=[month * kept for month in months],
        top_up=sum(months, Decimal(0)) * tax.top_up,
        withheld=tax.withheld,
        tax_basis=tax.basis,
    )


def combine(estimates: list[Estimate]) -> list[Estimate]:
    """One row per asset: an asset held in two portfolios sums its
    quantities and amounts; what Yahoo says about it is the same in both.
    Its tax rate is shown only when every holding has the same one -- an
    IKE and a regular account holding the same company differ."""
    by_key: dict[str, list[Estimate]] = {}
    for item in estimates:
        by_key.setdefault(item.key, []).append(item)
    rows = []
    for items in by_key.values():
        lead = min(items, key=lambda i: ("yahoo", "history", "none").index(i.source))
        rows.append(
            Estimate(
                key=lead.key,
                name=lead.name,
                quantity=sum((i.quantity for i in items), Decimal(0)),
                source=lead.source,
                per_share=lead.per_share,
                currency=lead.currency,
                months=[sum(month, Decimal(0)) for month in zip(*(i.months for i in items))],
                yield_fraction=lead.yield_fraction,
                mismatch=any(i.mismatch for i in items),
                missing_currency=next(
                    (i.missing_currency for i in items if i.missing_currency), None
                ),
                credited_months=[
                    sum(month, Decimal(0)) for month in zip(*(i.credited_months for i in items))
                ],
                top_up=sum((i.top_up for i in items), Decimal(0)),
                **_shared_tax(items),
            )
        )
    rows.sort(key=lambda r: (-r.total, r.name))
    return rows


def _shared_tax(items: list[Estimate]) -> dict:
    taxes = {(i.withheld, i.tax_basis) for i in items}
    if len(taxes) == 1:
        withheld, basis = taxes.pop()
        return {"withheld": withheld, "tax_basis": basis}
    return {"withheld": None, "tax_basis": "mixed"}


def normalized_currency(quote_currency: str) -> tuple[str, Decimal]:
    """(ISO code, how many quote units make one unit of it)."""
    return _MINOR_UNITS.get(quote_currency, (quote_currency, Decimal(1)))


def _yahoo_dividends(
    listing: YahooListing | None, since: date, today: date
) -> list[PerShareDividend] | None:
    """The listing's payouts in the window, in an ISO currency -- or None
    when Yahoo can't speak for the instrument at all."""
    if listing is None or listing.latest_close is None or listing.quote_currency is None:
        return None
    currency, divisor = normalized_currency(listing.quote_currency)
    return [
        PerShareDividend(day, amount / divisor, currency)
        for day, amount in listing.dividends
        if since < day <= today
    ]


def _yield(listing: YahooListing | None, since: date, today: date) -> Decimal | None:
    # Both in the quote unit, so the ratio needs no exchange rate.
    if listing is None or not listing.latest_close:
        return None
    paid = sum((a for day, a in listing.dividends if since < day <= today), Decimal(0))
    return paid / listing.latest_close


def _differ(
    yahoo: list[PerShareDividend], own: list[PerShareDividend], rates: dict[str, Decimal]
) -> bool:
    if not own:
        return False
    if any(d.currency not in rates for d in [*yahoo, *own]):
        return False
    if not yahoo:
        return True  # the account was paid, Yahoo lists nothing

    def average(payouts: list[PerShareDividend]) -> Decimal:
        return sum((d.amount * rates[d.currency] for d in payouts), Decimal(0)) / len(payouts)

    a, b = average(yahoo), average(own)
    larger = max(abs(a), abs(b))
    return larger > 0 and abs(a - b) / larger > MISMATCH_TOLERANCE
