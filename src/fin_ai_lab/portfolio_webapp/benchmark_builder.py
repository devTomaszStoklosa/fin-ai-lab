"""Gathers what benchmark.py needs -- dividend-adjusted daily closes from
yfinance, the quote currency, NBP rates -- and returns the API's
BenchmarkOut on the valuation's day axis (fin-ai-lab#273). All network
access goes through the injected fetchers/client, so tests run on canned
series."""

import asyncio
from collections.abc import Callable
from datetime import date, timedelta
from decimal import ROUND_HALF_UP

from fin_ai_lab.portfolio_webapp.benchmark import benchmark_series, find_benchmark
from fin_ai_lab.portfolio_webapp.schemas import BenchmarkOut
from fin_ai_lab.portfolio_webapp.valuation import (
    BASE_CURRENCY,
    MissingFxRateError,
    day_range,
    fx_currency_code,
)
from fin_ai_lab.portfolio_webapp.valuation_builder import (
    INDEX,
    MAX_HISTORY_DAYS,
    DailyClosesFetcher,
    FxSeriesClient,
)


class BenchmarkNotFoundError(Exception):
    """Yahoo has no closes (or no currency) for the ticker."""


class BenchmarkUnavailableError(Exception):
    """Yahoo did not answer -- yfinance is unofficial and sometimes blocked
    (docs/DATA-SOURCES.md)."""


async def build_benchmark(
    ticker: str,
    *,
    start: date,
    today: date,
    refresh: bool,
    closes_fetcher: DailyClosesFetcher,
    quote_currency_fetcher: Callable[[str], str | None],
    fx_client: FxSeriesClient,
) -> BenchmarkOut:
    """`ticker` is already normalized (benchmark.normalize_ticker). `start`
    is the valuation's first day, capped like the valuation's own window."""
    start = max(min(start, today), today - timedelta(days=MAX_HISTORY_DAYS))
    days = day_range(start, today)
    # First of the month, like build_valuation: one benchmark asked for from
    # the start page and a portfolio page mostly shares its cache entry.
    fetch_start = (start - timedelta(days=10)).replace(day=1)
    try:
        closes = await asyncio.to_thread(closes_fetcher, ticker, fetch_start, refresh)
    except Exception as exc:
        raise BenchmarkUnavailableError(ticker) from exc
    if not closes:
        raise BenchmarkNotFoundError(ticker)
    # Asked only once Yahoo has answered with closes: for a symbol it does
    # not know, yfinance's fast_info raises (KeyError 'currency') instead of
    # returning None -- that is "unknown ticker", not "Yahoo is down".
    try:
        quote_currency = await asyncio.to_thread(quote_currency_fetcher, ticker)
    except Exception as exc:
        raise BenchmarkNotFoundError(ticker) from exc
    if not quote_currency:
        raise BenchmarkNotFoundError(ticker)

    currency = fx_currency_code(quote_currency)
    fx_rates = {}
    if currency != BASE_CURRENCY:
        try:
            fx_rates[currency] = await fx_client.mid_rate_series(currency, fetch_start, today)
        except Exception as exc:
            # NBP publishes no rate for it, or did not answer: either way
            # there is no honest PLN value.
            raise MissingFxRateError(currency) from exc

    series = benchmark_series(closes, quote_currency, days, fx_rates)
    if series is None:
        raise BenchmarkNotFoundError(ticker)
    known = find_benchmark(ticker)
    return BenchmarkOut(
        ticker=ticker,
        label=known.label if known else ticker,
        note=known.note if known else None,
        quote_currency=quote_currency,
        base_currency=BASE_CURRENCY,
        dates=days,
        values=[value.quantize(INDEX, rounding=ROUND_HALF_UP) for value in series.values],
        first_price_date=series.first_price_date,
        prices_as_of=series.prices_as_of,
    )
