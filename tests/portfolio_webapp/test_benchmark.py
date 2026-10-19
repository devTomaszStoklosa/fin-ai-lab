from datetime import date
from decimal import Decimal

import pytest

from fin_ai_lab.portfolio_webapp.benchmark import (
    BENCHMARKS,
    benchmark_series,
    find_benchmark,
    normalize_ticker,
)
from fin_ai_lab.portfolio_webapp.valuation import MissingFxRateError, day_range

D = Decimal


def _days(start: str, end: str) -> list[date]:
    return day_range(date.fromisoformat(start), date.fromisoformat(end))


def _closes(values: dict[str, str]) -> dict[date, Decimal]:
    return {date.fromisoformat(day): D(value) for day, value in values.items()}


def test_normalize_ticker_upper_cases_yahoo_symbols() -> None:
    assert normalize_ticker(" aapl ") == "AAPL"
    assert normalize_ticker("^sp500tr") == "^SP500TR"
    assert normalize_ticker("GC=F") == "GC=F"
    assert normalize_ticker("etfbw20tr.wa") == "ETFBW20TR.WA"


@pytest.mark.parametrize("ticker", ["", "../etc/passwd", "AAPL MSFT", "A" * 21, "ŻABKA"])
def test_normalize_ticker_rejects_what_cannot_be_a_ticker(ticker: str) -> None:
    assert normalize_ticker(ticker) is None


def test_every_built_in_benchmark_is_found_by_its_normalized_ticker() -> None:
    for benchmark in BENCHMARKS:
        assert normalize_ticker(benchmark.ticker) == benchmark.ticker
        assert find_benchmark(benchmark.ticker) == benchmark
    assert find_benchmark("AAPL") is None


def test_pln_benchmark_is_the_close_ratio_with_weekends_carried() -> None:
    days = _days("2026-01-02", "2026-01-05")  # Fri, Sat, Sun, Mon
    closes = _closes({"2025-12-31": "90", "2026-01-02": "100", "2026-01-05": "110"})

    series = benchmark_series(closes, "PLN", days, {})

    assert series is not None
    assert series.values == [D(1), D(1), D(1), D("1.1")]
    assert series.first_price_date == date(2026, 1, 2)
    assert series.prices_as_of == date(2026, 1, 5)


def test_foreign_benchmark_moves_with_the_nbp_rate_too() -> None:
    # Price +10%, USD/PLN 4.00 -> 3.80: in PLN 1.1 x 0.95 = 1.045.
    days = _days("2026-01-05", "2026-01-06")
    closes = _closes({"2026-01-05": "100", "2026-01-06": "110"})
    fx = {"USD": _closes({"2026-01-05": "4.00", "2026-01-06": "3.80"})}

    series = benchmark_series(closes, "USD", days, fx)

    assert series is not None
    assert series.values == [D(1), D("1.045")]


def test_pence_quote_moves_with_the_pound_rate() -> None:
    days = _days("2026-01-05", "2026-01-06")
    closes = _closes({"2026-01-05": "10000", "2026-01-06": "10100"})
    fx = {"GBP": _closes({"2026-01-05": "5.00", "2026-01-06": "5.00"})}

    series = benchmark_series(closes, "GBp", days, fx)

    assert series is not None
    assert series.values == [D(1), D("1.01")]


def test_days_before_the_first_price_stay_at_one() -> None:
    days = _days("2026-01-01", "2026-01-04")
    closes = _closes({"2026-01-03": "50", "2026-01-04": "55"})

    series = benchmark_series(closes, "PLN", days, {})

    assert series is not None
    assert series.first_price_date == date(2026, 1, 3)
    assert series.values == [D(1), D(1), D(1), D("1.1")]


def test_no_close_up_to_the_last_day_is_no_series() -> None:
    closes = _closes({"2026-02-01": "50"})

    assert benchmark_series(closes, "PLN", _days("2026-01-01", "2026-01-02"), {}) is None


def test_quote_currency_without_an_nbp_series_raises() -> None:
    closes = _closes({"2026-01-05": "100"})

    with pytest.raises(MissingFxRateError):
        benchmark_series(closes, "XYZ", _days("2026-01-05", "2026-01-05"), {})
