"""Gathers what dividend_forecast.py needs for one or more portfolios -- what
each holds today, the per-share amounts XTB stated for its own payments,
Yahoo's dividends, quote currency and latest close per ticker, today's NBP
rates, and each holding's tax by its account type and issuer (#267) -- and
turns the estimate into the API's DividendForecastOut (#266).
Yahoo and NBP access go through injected fetchers, so tests run offline."""

import asyncio
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

import duckdb

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.cash_operations import CashOperation, dividend_per_share
from fin_ai_lab.portfolio_webapp.dividend_forecast import (
    MONTHS_IN_YEAR,
    Estimate,
    Holding,
    PerShareDividend,
    YahooListing,
    combine,
    estimate,
    normalized_currency,
)
from fin_ai_lab.portfolio_webapp.dividend_tax import dividend_tax, issuer_country
from fin_ai_lab.portfolio_webapp.dividends import DividendLinker
from fin_ai_lab.portfolio_webapp.dividends_builder import dividend_linker
from fin_ai_lab.portfolio_webapp.instruments_builder import LinkState, load_link_state
from fin_ai_lab.portfolio_webapp.lot_history import xtb_key
from fin_ai_lab.portfolio_webapp.lots import XTB_BROKER
from fin_ai_lab.portfolio_webapp.repository import PortfolioRow, PositionRow
from fin_ai_lab.portfolio_webapp.schemas import DividendForecastOut, DividendForecastRowOut
from fin_ai_lab.portfolio_webapp.valuation import BASE_CURRENCY, base_rate_lookup
from fin_ai_lab.portfolio_webapp.valuation_builder import DailyClosesFetcher, FxSeriesClient
from fin_ai_lab.portfolio_webapp.yahoo_ticker import position_yahoo_ticker

# ticker -> per-share dividends by ex-date, in the quote unit.
DividendsFetcher = Callable[[str], list[tuple[date, Decimal]]]
QuoteCurrencyFetcher = Callable[[str], str | None]

MONEY = Decimal("0.01")
PER_SHARE = Decimal("0.0001")
PERCENT = Decimal("0.1")
# Long enough to hold the last close and the last NBP rate through a long
# weekend or holiday break.
LOOKBACK = timedelta(days=14)
# Modest on purpose: yfinance is unofficial and sometimes blocks bursts
# (docs/DATA-SOURCES.md) -- same limit as the valuation's price lookups.
YAHOO_FETCH_CONCURRENCY = 4


async def build_dividend_forecast(
    connection: duckdb.DuckDBPyConnection,
    portfolio_rows: list[PortfolioRow],
    *,
    today: date,
    fx_client: FxSeriesClient,
    dividends_fetcher: DividendsFetcher,
    quote_currency_fetcher: QuoteCurrencyFetcher,
    closes_fetcher: DailyClosesFetcher,
    link_state: LinkState | None = None,
) -> DividendForecastOut:
    if link_state is None:
        link_state = load_link_state(connection)
    in_scope = {row[0] for row in portfolio_rows}
    held = [
        (portfolio[0], row)
        for portfolio, row in repository.list_current_positions(connection)
        if portfolio[0] in in_scope and row[8] > 0
    ]
    own: dict[UUID, dict[str, list[PerShareDividend]]] = {}
    observed: dict[UUID, dict[str, Decimal]] = {}
    for portfolio in portfolio_rows:
        operations = repository.list_cash_operations(connection, portfolio[0])
        own[portfolio[0]] = _own_per_share(operations)
        observed[portfolio[0]] = _observed_withholding(
            operations, dividend_linker(connection, portfolio)
        )
    account_types = {portfolio[0]: portfolio[3] for portfolio in portfolio_rows}
    tickers = sorted({ticker for _, row in held if (ticker := _yahoo_ticker(row)) is not None})
    listings = await _fetch_listings(
        tickers, today, dividends_fetcher, quote_currency_fetcher, closes_fetcher
    )

    holdings = []
    for portfolio_id, row in held:
        key = repository.position_key(row)
        asset_key = link_state.identities.asset_key(key)
        ticker = _yahoo_ticker(row)
        country = issuer_country(
            isin=row[5] or asset_key, xtb_symbol=row[6] if row[2] == XTB_BROKER else None
        )
        holdings.append(
            Holding(
                key=asset_key,
                name=row[4],
                quantity=row[8],
                listing=listings.get(ticker) if ticker is not None else None,
                own=own[portfolio_id].get(key, []),
                tax=dividend_tax(
                    account_type=account_types[portfolio_id],
                    country=country,
                    observed=observed[portfolio_id].get(key),
                ),
            )
        )

    rates = await _today_rates(fx_client, holdings, today)
    rows = combine([estimate(holding, today=today, rates=rates) for holding in holdings])
    # A row without an NBP rate has all-zero months, so it adds nothing.
    months = [
        sum((row.months[month] for row in rows), Decimal(0)) for month in range(MONTHS_IN_YEAR)
    ]
    credited = [
        sum((row.credited_months[month] for row in rows), Decimal(0))
        for month in range(MONTHS_IN_YEAR)
    ]
    return DividendForecastOut(
        base_currency=BASE_CURRENCY,
        year=today.year + 1,
        total=_money(sum(months, Decimal(0))),
        months=[_money(month) for month in months],
        total_credited=_money(sum(credited, Decimal(0))),
        months_credited=[_money(month) for month in credited],
        total_top_up=_money(sum((row.top_up for row in rows), Decimal(0))),
        rows=[_row_out(row) for row in rows],
        warnings=_warnings(rows),
    )


def _own_per_share(operations: list[CashOperation]) -> dict[str, list[PerShareDividend]]:
    """XTB's own statement of each dividend per share, by instrument key.
    Corrections and tax rows state no per-share amount and are skipped."""
    by_key: dict[str, list[PerShareDividend]] = {}
    for operation in operations:
        if operation.kind != "dividend" or operation.ticker is None:
            continue
        stated = dividend_per_share(operation.comment)
        if stated is None:
            continue
        currency, amount = stated
        by_key.setdefault(xtb_key(operation.ticker), []).append(
            PerShareDividend(operation.occurred_at.date(), amount, currency)
        )
    return by_key


def _observed_withholding(
    operations: list[CashOperation], linker: DividendLinker
) -> dict[str, Decimal]:
    """The withholding rate the latest statement gave each instrument's
    dividend (XTB "WHT 15%", Bossa "netto 85%"), by instrument key."""
    latest: dict[str, tuple[datetime, Decimal]] = {}
    for operation in operations:
        if operation.kind != "dividend":
            continue
        source = linker.link(operation)
        if source.instrument_key is None or source.withheld is None or source.is_correction:
            continue
        known = latest.get(source.instrument_key)
        if known is None or operation.occurred_at >= known[0]:
            latest[source.instrument_key] = (operation.occurred_at, source.withheld)
    return {key: rate for key, (_, rate) in latest.items()}


async def _fetch_listings(
    tickers: list[str],
    today: date,
    dividends_fetcher: DividendsFetcher,
    quote_currency_fetcher: QuoteCurrencyFetcher,
    closes_fetcher: DailyClosesFetcher,
) -> dict[str, YahooListing]:
    semaphore = asyncio.Semaphore(YAHOO_FETCH_CONCURRENCY)

    async def one(ticker: str) -> tuple[str, YahooListing]:
        async with semaphore:
            try:
                closes = await asyncio.to_thread(closes_fetcher, ticker, today - LOOKBACK, False)
                dividends = await asyncio.to_thread(dividends_fetcher, ticker)
                currency = await asyncio.to_thread(quote_currency_fetcher, ticker)
            except Exception:
                # yfinance is unofficial and sometimes blocked: one failed
                # ticker falls back to the account's own history, never a 500.
                return ticker, YahooListing([], None, None)
        latest = closes[max(closes)] if closes else None
        return ticker, YahooListing(dividends, currency, latest)

    return dict(await asyncio.gather(*(one(ticker) for ticker in tickers)))


async def _today_rates(
    fx_client: FxSeriesClient, holdings: list[Holding], today: date
) -> dict[str, Decimal]:
    currencies = {d.currency for h in holdings for d in h.own}
    currencies |= {
        normalized_currency(h.listing.quote_currency)[0]
        for h in holdings
        if h.listing is not None and h.listing.quote_currency is not None
    }
    rates = {BASE_CURRENCY: Decimal(1)}
    for currency in sorted(currencies - {BASE_CURRENCY}):
        try:
            series = await fx_client.mid_rate_series(currency, today - LOOKBACK, today)
            rates[currency] = base_rate_lookup(currency, {currency: series})(today)
        except Exception:
            # NBP down or no series (MissingFxRateError): left out of
            # `rates`, so the estimate reports the currency as missing.
            continue
    return rates


def _row_out(row: Estimate) -> DividendForecastRowOut:
    return DividendForecastRowOut(
        instrument_key=row.key,
        name=row.name,
        quantity=row.quantity,
        per_share=row.per_share.quantize(PER_SHARE, ROUND_HALF_UP)
        if row.per_share is not None
        else None,
        per_share_currency=row.currency,
        estimate=_money(row.total),
        credited=_money(row.credited),
        top_up=_money(row.top_up),
        withholding_pct=(row.withheld * 100).quantize(PERCENT, ROUND_HALF_UP)
        if row.withheld is not None
        else None,
        tax_basis=row.tax_basis,
        yield_pct=(row.yield_fraction * 100).quantize(PERCENT, ROUND_HALF_UP)
        if row.yield_fraction is not None
        else None,
        source=row.source,
        mismatch=row.mismatch,
    )


def _warnings(rows: list[Estimate]) -> list[str]:
    warnings = []
    missing: dict[str, list[str]] = {}
    for row in rows:
        if row.missing_currency is not None:
            missing.setdefault(row.missing_currency, []).append(row.name)
    for currency, names in sorted(missing.items()):
        warnings.append(
            f"Brak kursu NBP dla {currency} — pominięte w szacunku: {', '.join(names)}."
        )
    unknown = [row.name for row in rows if row.source == "none"]
    if unknown:
        warnings.append(
            "Brak danych o dywidendach (Yahoo nie zna instrumentu, brak własnych wypłat): "
            + ", ".join(unknown)
            + "."
        )
    unknown_tax = [row.name for row in rows if row.tax_basis == "unknown" and row.total > 0]
    if unknown_tax:
        warnings.append(
            "Nieznana stawka podatku (typ konta albo kraj spółki) — „na konto” liczone brutto: "
            + ", ".join(unknown_tax)
            + "."
        )
    differing = [row.name for row in rows if row.mismatch]
    if differing:
        warnings.append(
            "Yahoo i wyciąg XTB podają różne kwoty na jedną wypłatę (ponad 25%) — np. inna "
            "waluta albo dywidenda w ratach; szacunek liczony z Yahoo: "
            + ", ".join(differing)
            + "."
        )
    return warnings


def _yahoo_ticker(row: PositionRow) -> str | None:
    return position_yahoo_ticker(
        broker=row[2], symbol=row[6], ticker=row[16], exchange_code=row[17]
    )


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)
