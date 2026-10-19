"""Benchmarks for the value chart's comparison mode (fin-ai-lab#273) --
pure computation: the built-in list, the ticker check, and a benchmark's
series in PLN. benchmark_builder.py fetches the closes and NBP rates and
hands them here, so each rule is testable on hand-made numbers.

Every series includes dividends, as the portfolio's own return does
(valuation.return_index counts the dividends credited): a total-return
index, a fund that reinvests them, or dividend-adjusted closes. Yahoo has
no history for the GPW indices themselves (WIG20.WA, WIG.WA, MWIG40.WA
return today's quote only; ^XNDX for Nasdaq-100 TR likewise -- checked live
2026-10-13), hence the funds below in their place.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fin_ai_lab.portfolio_webapp.valuation import Anchor, fx_currency_code, unit_value_series


@dataclass(frozen=True)
class Benchmark:
    id: str
    label: str
    ticker: str
    note: str  # what the series is, in the page's language


BENCHMARKS = (
    Benchmark(
        "wig20", "WIG20", "ETFBW20TR.WA", "Beta ETF WIG20TR — fundusz na WIG20 z dywidendami"
    ),
    Benchmark(
        "mwig40", "mWIG40", "ETFBM40TR.WA", "Beta ETF mWIG40TR — fundusz na mWIG40 z dywidendami"
    ),
    Benchmark("sp500", "S&P 500", "^SP500TR", "S&P 500 Total Return — indeks z dywidendami"),
    Benchmark(
        "nasdaq100", "Nasdaq-100", "QQQ", "Invesco QQQ — fundusz na Nasdaq-100, kurs z dywidendami"
    ),
    Benchmark("dax", "DAX", "^GDAXI", "DAX — indeks liczony z dywidendami"),
    Benchmark(
        "msci_world",
        "MSCI World",
        "IWDA.AS",
        "iShares Core MSCI World — fundusz reinwestujący dywidendy",
    ),
    Benchmark("gold", "Złoto", "GC=F", "kontrakt na złoto — złoto nie płaci dywidend"),
)

# Yahoo symbols: letters, digits and ". ^ = -" (^SP500TR, GC=F, BRK-B,
# ETFBW20TR.WA). Anything else is not a ticker -- and never reaches yfinance
# or a cache file name.
_TICKER = re.compile(r"[A-Z0-9.^=\-]{1,20}")


def normalize_ticker(ticker: str) -> str | None:
    """The ticker as Yahoo spells it (upper case), or None if it can't be one."""
    normalized = ticker.strip().upper()
    return normalized if _TICKER.fullmatch(normalized) else None


def find_benchmark(ticker: str) -> Benchmark | None:
    return next((b for b in BENCHMARKS if b.ticker == ticker), None)


@dataclass(frozen=True)
class BenchmarkSeries:
    values: list[Decimal]  # per day: 1 on first_price_date, the PLN ratio after it
    first_price_date: date
    prices_as_of: date  # the last close used


def benchmark_series(
    closes: dict[date, Decimal],
    quote_currency: str,
    days: list[date],
    fx_rates: dict[str, dict[date, Decimal]],
) -> BenchmarkSeries | None:
    """The benchmark in PLN, day by day, as an index: 1 on the first day with
    a price, then close(d) x FX(d) / (close(first) x FX(first)) -- what 1 PLN
    put into it that day was worth, currency moves included, as the
    portfolio's PLN value includes them. The same price-ratio-times-FX-ratio
    rule as a position's unit value (valuation.unit_value_series), so a
    pence quote (GBp) needs nothing of its own. Weekends and holidays reuse
    the last close; days before the first price stay at 1.

    None without any close on or before the last day. Raises
    MissingFxRateError when NBP has no rate series for the quote currency."""
    known = sorted(day for day in closes if day <= days[-1])
    if not known:
        return None
    first_price_date = max(days[0], known[0])
    first_index = (first_price_date - days[0]).days
    anchor = Anchor(
        unit_value=Decimal(1), currency=fx_currency_code(quote_currency), as_of=first_price_date
    )
    base = unit_value_series(anchor, days, closes, fx_rates).base
    start_value = base[first_index]
    values = [
        Decimal(1) if index < first_index else value / start_value
        for index, value in enumerate(base)
    ]
    return BenchmarkSeries(values=values, first_price_date=first_price_date, prices_as_of=known[-1])
