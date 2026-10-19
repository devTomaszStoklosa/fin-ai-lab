"""Dividend history of one or more portfolios (fin-ai-lab#265) -- pure
computation, no database, no network.

A payment is what one dividend put into the account. XTB books a dividend
and the tax withheld from it as two rows of the same moment; they are joined
here into one payment whose amount is what was credited. Bossa books one row
per payment, already after tax. Nothing here reasons about tax itself (#267).

Each payment is linked to the instrument it came from where the import says
so: XTB by its Ticker column, Bossa by the name or ticker in the operation
title (DividendLinker, one per broker). A payment that can't be linked still
counts, under the name its row gives.

Amounts are converted at the NBP rate of the payment's own day -- the same
rule as investment_result.py, so the history's total is the investment
result's `dividends`.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from fin_ai_lab.portfolio_webapp.bossa_financial import parse_dividend_title
from fin_ai_lab.portfolio_webapp.cash_operations import CashOperation, withholding_rate
from fin_ai_lab.portfolio_webapp.instruments import display_name
from fin_ai_lab.portfolio_webapp.lot_history import xtb_key
from fin_ai_lab.portfolio_webapp.valuation import MissingFxRateError, base_rate_lookup

# XTB marks a correction of an earlier dividend in its comment:
# "corr ATR.PL USD 0.5700/ SHR".
_XTB_CORRECTION_PREFIX = "corr "
LAST_12_MONTHS = timedelta(days=365)
MONTHS_IN_YEAR = 12


@dataclass(frozen=True)
class PaymentSource:
    """The instrument a dividend row came from. `instrument_key` is None when
    the row names nothing the portfolio holds or traded; `name` is then the
    row's own label."""

    instrument_key: str | None
    name: str
    is_correction: bool = False
    # #267: the tax withheld at source as this row states it (0.15), when it
    # does -- XTB on its tax rows, Bossa in the title. Not used by the
    # history itself, which counts what was credited.
    withheld: Decimal | None = None


class DividendLinker(Protocol):
    def link(self, operation: CashOperation) -> PaymentSource: ...


class XtbDividendLinker:
    """XTB names the instrument by its own symbol ("MSFT.US"), the one its
    positions are keyed by. A row stored before the Ticker column was read
    has only the name, and stays unlinked until the file is imported again."""

    def link(self, operation: CashOperation) -> PaymentSource:
        name = operation.instrument or operation.ticker or operation.op_type
        is_correction = (operation.comment or "").startswith(_XTB_CORRECTION_PREFIX)
        key = xtb_key(operation.ticker) if operation.ticker else None
        return PaymentSource(key, name, is_correction, withholding_rate(operation.comment))


class BossaDividendLinker:
    """Bossa names the company in the title only: by its short name for a GPW
    share ("PEKAO", the name its trades use too) or by its ticker abroad
    ("HCA", the OpenFIGI ticker of a position or of a listing the ledger
    traded).

    `by_name` and `by_ticker` map a name or ticker to (instrument key,
    instrument name); case is ignored."""

    def __init__(
        self, by_name: dict[str, tuple[str, str]], by_ticker: dict[str, tuple[str, str]]
    ) -> None:
        self._by_name = {name.casefold(): match for name, match in by_name.items()}
        self._by_ticker = {ticker.casefold(): match for ticker, match in by_ticker.items()}

    def link(self, operation: CashOperation) -> PaymentSource:
        title = parse_dividend_title(operation.op_type)
        if title is None:
            return PaymentSource(None, operation.op_type)
        code = title.code.casefold()
        match = self._by_name.get(code) or self._by_ticker.get(code)
        if match is None:
            return PaymentSource(None, title.code, title.is_correction, title.withheld)
        key, name = match
        return PaymentSource(key, name, title.is_correction, title.withheld)


@dataclass(frozen=True)
class DividendPayment:
    portfolio_id: UUID
    paid_on: date
    source: PaymentSource
    amount: Decimal  # credited (signed: a correction can take money back), in `currency`
    currency: str


@dataclass(frozen=True)
class ConvertedPayment:
    payment: DividendPayment
    rate: Decimal | None  # None: no NBP series for the payment's currency
    base_amount: Decimal | None


@dataclass(frozen=True)
class YearTotal:
    year: int
    total: Decimal
    months: list[Decimal]  # January first


@dataclass(frozen=True)
class InstrumentTotal:
    instrument_key: str | None  # the asset key; None for unlinked payments
    name: str
    payment_count: int
    last_paid_on: date
    total: Decimal
    last_12_months: Decimal


@dataclass(frozen=True)
class DividendHistory:
    total: Decimal
    last_12_months: Decimal
    current_year: Decimal
    years: list[YearTotal]  # oldest first, every year up to today's
    instruments: list[InstrumentTotal]  # largest total first
    missing_currencies: list[str]  # payments in these were left out of the sums


def dividend_payments(
    portfolio_id: UUID, operations: Iterable[CashOperation], linker: DividendLinker
) -> list[DividendPayment]:
    """One payment per instrument, day, currency and correction flag: XTB's
    dividend row and its withholding-tax row (same moment) become one."""
    grouped: dict[tuple[str, date, str, bool], DividendPayment] = {}
    for operation in operations:
        if operation.kind != "dividend":
            continue
        source = linker.link(operation)
        day = operation.occurred_at.date()
        group = (
            source.instrument_key or source.name,
            day,
            operation.currency,
            source.is_correction,
        )
        known = grouped.get(group)
        if known is None:
            grouped[group] = DividendPayment(
                portfolio_id, day, source, operation.amount, operation.currency
            )
        else:
            grouped[group] = DividendPayment(
                portfolio_id, day, known.source, known.amount + operation.amount, known.currency
            )
    return sorted(grouped.values(), key=lambda p: p.paid_on)


def convert_payments(
    payments: Iterable[DividendPayment], fx_rates: dict[str, dict[date, Decimal]]
) -> list[ConvertedPayment]:
    lookups: dict[str, Callable[[date], Decimal] | None] = {}
    converted = []
    for payment in payments:
        if payment.currency not in lookups:
            try:
                lookups[payment.currency] = base_rate_lookup(payment.currency, fx_rates)
            except MissingFxRateError:
                lookups[payment.currency] = None
        lookup = lookups[payment.currency]
        rate = lookup(payment.paid_on) if lookup is not None else None
        base_amount = payment.amount * rate if rate is not None else None
        converted.append(ConvertedPayment(payment, rate, base_amount))
    return converted


def summarize(
    payments: list[ConvertedPayment], *, today: date, asset_key: Callable[[str], str]
) -> DividendHistory:
    """`asset_key` maps a per-broker instrument key to its asset (S12), so one
    company paying into two accounts is one instrument row."""
    counted = [p for p in payments if p.base_amount is not None]
    recent_since = today - LAST_12_MONTHS
    first_year = min((p.payment.paid_on.year for p in payments), default=today.year)
    months = {year: [Decimal(0)] * MONTHS_IN_YEAR for year in range(first_year, today.year + 1)}
    for converted in counted:
        paid_on = converted.payment.paid_on
        if paid_on.year in months and converted.base_amount is not None:
            months[paid_on.year][paid_on.month - 1] += converted.base_amount
    years = [YearTotal(year, sum(m, Decimal(0)), m) for year, m in months.items()]

    groups: dict[str, list[ConvertedPayment]] = {}
    for converted in payments:
        groups.setdefault(_group(converted.payment.source, asset_key), []).append(converted)
    instruments = [
        _instrument_total(members, asset_key, recent_since) for members in groups.values()
    ]
    instruments.sort(key=lambda i: (-i.total, i.name))

    def total(selected: Iterable[ConvertedPayment]) -> Decimal:
        return sum((p.base_amount for p in selected if p.base_amount is not None), Decimal(0))

    return DividendHistory(
        total=total(counted),
        last_12_months=total(p for p in counted if p.payment.paid_on > recent_since),
        current_year=total(p for p in counted if p.payment.paid_on.year == today.year),
        years=years,
        instruments=instruments,
        missing_currencies=sorted({p.payment.currency for p in payments if p.rate is None}),
    )


def payment_asset_key(source: PaymentSource, asset_key: Callable[[str], str]) -> str | None:
    return asset_key(source.instrument_key) if source.instrument_key is not None else None


def _group(source: PaymentSource, asset_key: Callable[[str], str]) -> str:
    key = payment_asset_key(source, asset_key)
    # Unlinked payments group by their label, so one company paying into two
    # accounts under the same short name is still one row.
    return key if key is not None else f"unlinked:{source.name.casefold()}"


def _instrument_total(
    members: list[ConvertedPayment], asset_key: Callable[[str], str], recent_since: date
) -> InstrumentTotal:
    sources = [m.payment.source for m in members]
    return InstrumentTotal(
        instrument_key=payment_asset_key(sources[0], asset_key),
        name=display_name(list(dict.fromkeys(s.name for s in sources))),
        payment_count=len(members),
        last_paid_on=max(m.payment.paid_on for m in members),
        total=sum((m.base_amount for m in members if m.base_amount is not None), Decimal(0)),
        last_12_months=sum(
            (
                m.base_amount
                for m in members
                if m.base_amount is not None and m.payment.paid_on > recent_since
            ),
            Decimal(0),
        ),
    )
