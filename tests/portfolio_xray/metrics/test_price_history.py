import sys
import types
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from fin_ai_lab.portfolio_xray.metrics.price_history import (  # noqa: E402
    fetch_daily_closes,
    fetch_dividends,
    fetch_price_history,
    fetch_quote_currency,
    price_change_ratio,
    to_yahoo_ticker,
)


def _install_fake_yfinance(
    monkeypatch: pytest.MonkeyPatch,
    history_df,
    call_count: dict | None = None,
    fast_info: dict | None = None,
) -> None:
    fake_module = types.ModuleType("yfinance")

    class FakeTicker:
        def __init__(self, ticker: str) -> None:
            self._ticker = ticker
            self.fast_info = fast_info or {}

        def history(self, period: str):
            if call_count is not None:
                call_count["n"] += 1
            return history_df

    fake_module.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_module)


def test_fetch_price_history_returns_series_and_caches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    index = pd.date_range("2026-01-01", periods=3)
    history_df = pd.DataFrame({"Close": [1.0, 2.0, 3.0]}, index=index)
    _install_fake_yfinance(monkeypatch, history_df)

    series = fetch_price_history("AAPL", cache_dir=tmp_path)

    assert list(series.to_numpy()) == [1.0, 2.0, 3.0]
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_fetch_price_history_uses_cache_on_second_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    call_count = {"n": 0}
    index = pd.date_range("2026-01-01", periods=2)
    history_df = pd.DataFrame({"Close": [1.0, 2.0]}, index=index)
    _install_fake_yfinance(monkeypatch, history_df, call_count)

    fetch_price_history("AAPL", cache_dir=tmp_path)
    fetch_price_history("AAPL", cache_dir=tmp_path)

    assert call_count["n"] == 1


def test_fetch_price_history_returns_none_for_empty_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    empty_df = pd.DataFrame({"Close": []})
    _install_fake_yfinance(monkeypatch, empty_df)

    series = fetch_price_history("UNKNOWN", cache_dir=tmp_path)

    assert series is None


def test_fetch_price_history_caches_none_result_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    call_count = {"n": 0}
    empty_df = pd.DataFrame({"Close": []})
    _install_fake_yfinance(monkeypatch, empty_df, call_count)

    fetch_price_history("UNKNOWN", cache_dir=tmp_path)
    fetch_price_history("UNKNOWN", cache_dir=tmp_path)

    assert call_count["n"] == 1


def test_price_change_ratio_divides_latest_close_by_reference_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    index = pd.date_range("2026-01-01", periods=5)
    history_df = pd.DataFrame({"Close": [10.0, 20.0, 30.0, 40.0, 50.0]}, index=index)
    _install_fake_yfinance(monkeypatch, history_df)

    ratio = price_change_ratio("AAPL", date(2026, 1, 2), cache_dir=tmp_path)

    assert ratio == Decimal("2.5")  # latest 50.0 / close on 2026-01-02 (20.0)


def test_price_change_ratio_uses_closest_prior_date_when_since_has_no_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    index = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"])
    history_df = pd.DataFrame({"Close": [10.0, 20.0, 30.0, 40.0]}, index=index)
    _install_fake_yfinance(monkeypatch, history_df)

    # 2026-01-03 has no close (weekend gap) -- falls back to 2026-01-02 (20.0).
    ratio = price_change_ratio("AAPL", date(2026, 1, 3), cache_dir=tmp_path)

    assert ratio == Decimal("2.0")  # latest 40.0 / 20.0


def test_price_change_ratio_returns_none_when_since_predates_all_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    index = pd.date_range("2026-01-01", periods=3)
    history_df = pd.DataFrame({"Close": [10.0, 20.0, 30.0]}, index=index)
    _install_fake_yfinance(monkeypatch, history_df)

    ratio = price_change_ratio("AAPL", date(2025, 12, 31), cache_dir=tmp_path)

    assert ratio is None


def test_price_change_ratio_returns_none_for_zero_reference_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    index = pd.date_range("2026-01-01", periods=2)
    history_df = pd.DataFrame({"Close": [0.0, 10.0]}, index=index)
    _install_fake_yfinance(monkeypatch, history_df)

    ratio = price_change_ratio("AAPL", date(2026, 1, 1), cache_dir=tmp_path)

    assert ratio is None


def test_price_change_ratio_returns_none_for_empty_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    empty_df = pd.DataFrame({"Close": []})
    _install_fake_yfinance(monkeypatch, empty_df)

    ratio = price_change_ratio("UNKNOWN", date(2026, 1, 1), cache_dir=tmp_path)

    assert ratio is None


def test_price_change_ratio_drops_trailing_nan_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Yahoo can return NaN for the most recent day before it finalizes --
    # must use the last REAL close (50.0), not the NaN one.
    index = pd.date_range("2026-01-01", periods=6)
    history_df = pd.DataFrame({"Close": [10.0, 20.0, 30.0, 40.0, 50.0, float("nan")]}, index=index)
    _install_fake_yfinance(monkeypatch, history_df)

    ratio = price_change_ratio("ISAC.L", date(2026, 1, 2), cache_dir=tmp_path)

    assert ratio == Decimal("2.5")  # 50.0 / 20.0


def test_to_yahoo_ticker_appends_mapped_suffix() -> None:
    assert to_yahoo_ticker("ISAC", "LN") == "ISAC.L"
    assert to_yahoo_ticker("ATR", "PW") == "ATR.WA"
    assert to_yahoo_ticker("ICHN", "NA") == "ICHN.AS"


def test_to_yahoo_ticker_returns_bare_ticker_for_unmapped_exchange() -> None:
    assert to_yahoo_ticker("AAPL", "US") == "AAPL"
    assert to_yahoo_ticker("AAPL", None) == "AAPL"


def test_fetch_quote_currency_returns_currency_and_caches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_yfinance(monkeypatch, pd.DataFrame({"Close": []}), fast_info={"currency": "USD"})

    currency = fetch_quote_currency("ISAC.L", cache_dir=tmp_path)

    assert currency == "USD"
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_fetch_quote_currency_uses_cache_on_second_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    construct_count = {"n": 0}
    fake_module = types.ModuleType("yfinance")

    class FakeTicker:
        def __init__(self, ticker: str) -> None:
            construct_count["n"] += 1
            self.fast_info = {"currency": "PLN"}

    fake_module.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_module)

    fetch_quote_currency("ATR.WA", cache_dir=tmp_path)
    fetch_quote_currency("ATR.WA", cache_dir=tmp_path)

    assert construct_count["n"] == 1


def test_fetch_quote_currency_returns_none_when_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_yfinance(monkeypatch, pd.DataFrame({"Close": []}), fast_info={})

    currency = fetch_quote_currency("UNKNOWN", cache_dir=tmp_path)

    assert currency is None


def _install_fake_daily_yfinance(
    monkeypatch: pytest.MonkeyPatch, history_df, calls: list[dict]
) -> None:
    fake_module = types.ModuleType("yfinance")

    class FakeTicker:
        def __init__(self, ticker: str) -> None:
            self._ticker = ticker

        def history(self, **kwargs):
            calls.append({"ticker": self._ticker, **kwargs})
            return history_df

    fake_module.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_module)


def test_fetch_daily_closes_asks_for_unadjusted_closes_from_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict] = []
    index = pd.to_datetime(["2026-01-02", "2026-01-05"])
    _install_fake_daily_yfinance(
        monkeypatch, pd.DataFrame({"Close": [10.5, 11.25]}, index=index), calls
    )

    closes = fetch_daily_closes("AAPL", date(2026, 1, 1), cache_dir=tmp_path)

    assert closes == {date(2026, 1, 2): Decimal("10.5"), date(2026, 1, 5): Decimal("11.25")}
    # Dividend-adjusted closes would quietly lower every past price.
    assert calls == [{"ticker": "AAPL", "start": "2026-01-01", "auto_adjust": False}]


def test_fetch_daily_closes_drops_unfinalized_nan_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    index = pd.to_datetime(["2026-01-02", "2026-01-05"])
    _install_fake_daily_yfinance(
        monkeypatch, pd.DataFrame({"Close": [10.0, float("nan")]}, index=index), []
    )

    closes = fetch_daily_closes("AAPL", date(2026, 1, 1), cache_dir=tmp_path)

    assert closes == {date(2026, 1, 2): Decimal("10.0")}


def test_fetch_daily_closes_uses_cache_unless_refresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict] = []
    index = pd.to_datetime(["2026-01-02"])
    _install_fake_daily_yfinance(monkeypatch, pd.DataFrame({"Close": [10.0]}, index=index), calls)

    first = fetch_daily_closes("AAPL", date(2026, 1, 1), cache_dir=tmp_path)
    second = fetch_daily_closes("AAPL", date(2026, 1, 1), cache_dir=tmp_path)
    fetch_daily_closes("AAPL", date(2026, 1, 1), refresh=True, cache_dir=tmp_path)

    assert first == second
    assert len(calls) == 2


def test_fetch_daily_closes_adjusted_reads_dividend_adjusted_closes_from_own_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict] = []
    index = pd.to_datetime(["2026-01-02", "2026-01-05"])
    history = pd.DataFrame({"Close": [10.0, 11.0], "Adj Close": [9.5, 10.6]}, index=index)
    _install_fake_daily_yfinance(monkeypatch, history, calls)

    plain = fetch_daily_closes("AAPL", date(2026, 1, 1), cache_dir=tmp_path)
    adjusted = fetch_daily_closes("AAPL", date(2026, 1, 1), adjusted=True, cache_dir=tmp_path)

    assert plain == {date(2026, 1, 2): Decimal("10.0"), date(2026, 1, 5): Decimal("11.0")}
    assert adjusted == {date(2026, 1, 2): Decimal("9.5"), date(2026, 1, 5): Decimal("10.6")}
    # Each kind has its own cache entry: the second call was not served the first's.
    assert len(calls) == 2


def test_fetch_daily_closes_returns_none_for_empty_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_daily_yfinance(monkeypatch, pd.DataFrame({"Close": []}), [])

    assert fetch_daily_closes("NOPE", date(2026, 1, 1), cache_dir=tmp_path) is None
    # "No data" is cached too -- a second call must not hit yfinance again.
    assert fetch_daily_closes("NOPE", date(2026, 1, 1), cache_dir=tmp_path) is None


def _install_fake_dividends_yfinance(
    monkeypatch: pytest.MonkeyPatch, dividends, call_count: dict
) -> None:
    fake_module = types.ModuleType("yfinance")

    class FakeTicker:
        def __init__(self, ticker: str) -> None:
            call_count["n"] += 1
            self.dividends = dividends

    fake_module.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_module)


def test_fetch_dividends_returns_per_share_amounts_by_ex_date_and_caches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = {"n": 0}
    index = pd.to_datetime(["2026-02-19", "2026-05-21", "2026-08-20"]).tz_localize(
        "America/New_York"
    )
    _install_fake_dividends_yfinance(
        monkeypatch, pd.Series([0.91, float("nan"), 0.91], index=index), calls
    )

    first = fetch_dividends("MSFT", cache_dir=tmp_path)
    second = fetch_dividends("MSFT", cache_dir=tmp_path)

    assert first == [(date(2026, 2, 19), Decimal("0.91")), (date(2026, 8, 20), Decimal("0.91"))]
    assert second == first
    assert calls["n"] == 1


def test_fetch_dividends_is_empty_for_a_listing_without_payouts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_dividends_yfinance(monkeypatch, pd.Series([], dtype=float), {"n": 0})

    assert fetch_dividends("AMZN", cache_dir=tmp_path) == []
