"""Gathers what dividends.py needs for one or more portfolios -- dividend
rows from the database, the names and tickers to link them by, NBP rate
series -- and turns its result into the API's DividendHistoryOut (#265).
NBP access goes through the injected client, so tests run on canned rates."""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import duckdb

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.dividends import (
    BossaDividendLinker,
    DividendLinker,
    DividendPayment,
    XtbDividendLinker,
    convert_payments,
    dividend_payments,
    payment_asset_key,
    summarize,
)
from fin_ai_lab.portfolio_webapp.instruments_builder import LinkState, load_link_state
from fin_ai_lab.portfolio_webapp.repository import PortfolioRow
from fin_ai_lab.portfolio_webapp.schemas import (
    DividendHistoryOut,
    DividendInstrumentOut,
    DividendPaymentOut,
    DividendYearOut,
)
from fin_ai_lab.portfolio_webapp.valuation import BASE_CURRENCY
from fin_ai_lab.portfolio_webapp.valuation_builder import FxSeriesClient

MONEY = Decimal("0.01")
RATE = Decimal("0.0001")
# NBP publishes no rate on weekends and holidays: start early enough that a
# payment on the first day still finds the last rate before it.
FX_LEAD_DAYS = 10


async def build_dividend_history(
    connection: duckdb.DuckDBPyConnection,
    portfolio_rows: list[PortfolioRow],
    *,
    today: date,
    fx_client: FxSeriesClient,
    link_state: LinkState | None = None,
) -> DividendHistoryOut:
    if link_state is None:
        link_state = load_link_state(connection)
    names = {row[0]: row[1] for row in portfolio_rows}
    payments: list[DividendPayment] = []
    for row in portfolio_rows:
        operations = repository.list_cash_operations(connection, row[0])
        if any(operation.kind == "dividend" for operation in operations):
            payments.extend(dividend_payments(row[0], operations, dividend_linker(connection, row)))

    fx_rates = await _fetch_fx(fx_client, payments, today)
    converted = convert_payments(payments, fx_rates)
    asset_key = link_state.identities.asset_key
    history = summarize(converted, today=today, asset_key=asset_key)

    warnings = [
        f"Brak kursu NBP dla {currency} — wypłaty w tej walucie pominięte w sumach."
        for currency in history.missing_currencies
    ]
    unlinked = sorted({i.name for i in history.instruments if i.instrument_key is None})
    if unlinked:
        warnings.append(
            "Wypłaty bez rozpoznanego instrumentu (liczą się do sum): " + ", ".join(unlinked) + "."
        )
    return DividendHistoryOut(
        base_currency=BASE_CURRENCY,
        total=_money(history.total),
        last_12_months=_money(history.last_12_months),
        current_year=_money(history.current_year),
        years=[
            DividendYearOut(
                year=year.year, total=_money(year.total), months=[_money(m) for m in year.months]
            )
            for year in history.years
        ],
        instruments=[
            DividendInstrumentOut(
                instrument_key=instrument.instrument_key,
                name=instrument.name,
                payment_count=instrument.payment_count,
                last_paid_on=instrument.last_paid_on,
                total=_money(instrument.total),
                last_12_months=_money(instrument.last_12_months),
            )
            for instrument in history.instruments
        ],
        payments=[
            DividendPaymentOut(
                paid_on=c.payment.paid_on,
                portfolio_id=c.payment.portfolio_id,
                portfolio_name=names[c.payment.portfolio_id],
                instrument_key=payment_asset_key(c.payment.source, asset_key),
                name=c.payment.source.name,
                amount=c.payment.amount,
                currency=c.payment.currency,
                fx_rate=c.rate.quantize(RATE, ROUND_HALF_UP) if c.rate is not None else None,
                amount_base=_money(c.base_amount) if c.base_amount is not None else None,
                is_correction=c.payment.source.is_correction,
            )
            for c in sorted(converted, key=lambda c: c.payment.paid_on, reverse=True)
        ],
        warnings=warnings,
    )


def dividend_linker(connection: duckdb.DuckDBPyConnection, row: PortfolioRow) -> DividendLinker:
    """A portfolio with a ledger is Bossa's; any other one with cash
    operations is XTB's -- the same split valuation_builder makes. Shared
    with the estimate (#267), which reads the tax rate rows state."""
    transactions = repository.list_transactions(connection, row[0])
    if not transactions:
        return XtbDividendLinker()
    by_name = {t.instrument_name: (t.isin, t.instrument_name) for t in transactions}
    by_ticker: dict[str, tuple[str, str]] = {}
    for snapshot in repository.list_snapshots(connection, row[0]):
        for position in repository.list_positions(connection, snapshot[0]):
            ticker = position[16]  # OpenFIGI's ticker
            if ticker:
                by_ticker.setdefault(ticker, (repository.position_key(position), position[4]))
    names = {t.isin: t.instrument_name for t in transactions}
    for ticker, match in _ledger_tickers(connection, names).items():
        by_ticker.setdefault(ticker, match)
    return BossaDividendLinker(by_name, by_ticker)


def _ledger_tickers(
    connection: duckdb.DuckDBPyConnection, names: dict[str, str]
) -> dict[str, tuple[str, str]]:
    """Ticker -> (ISIN, name) from the listing chosen for each ISIN the
    ledger traded (#277), sold ones included (#269): a held US stock often
    has no ticker of its own -- OpenFIGI's lookup at import stays ambiguous
    -- and a sold one has no position at all. A ticker two ISINs share links
    neither: an unlinked payment beats one booked to the wrong company."""
    listings = repository.list_instrument_listings(connection)
    isins_by_ticker: dict[str, set[str]] = {}
    for isin in names:
        listing = listings.get(isin)
        if listing is not None and listing.ticker:
            isins_by_ticker.setdefault(listing.ticker, set()).add(isin)
    linked: dict[str, tuple[str, str]] = {}
    for ticker, isins in isins_by_ticker.items():
        if len(isins) == 1:
            (isin,) = isins
            linked[ticker] = (isin, names[isin])
    return linked


async def _fetch_fx(
    fx_client: FxSeriesClient, payments: list[DividendPayment], today: date
) -> dict[str, dict[date, Decimal]]:
    currencies = sorted({p.currency for p in payments} - {BASE_CURRENCY})
    if not currencies:
        return {}
    start = min(p.paid_on for p in payments) - timedelta(days=FX_LEAD_DAYS)
    rates: dict[str, dict[date, Decimal]] = {}
    for currency in currencies:
        try:
            rates[currency] = await fx_client.mid_rate_series(currency, start, today)
        except Exception:
            # Reported by build_dividend_history as a missing currency.
            continue
    return rates


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)
