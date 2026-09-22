import sys
import types
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from fin_ai_lab.portfolio_xray.metrics.price_history import (  # noqa: E402
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
    history_df = pd.DataFrame(
        {"Close": [10.0, 20.0, 30.0, 40.0, 50.0, float("nan")]}, index=index
    )
    _install_fake_yfinance(monkeypatch, history_df)

    ratio = price_change_ratio("ISAC.L", date(2026, 1, 2), cache_dir=tmp_path)

    assert ratio == Decimal("2.5")  # 50.0 / 20.0


def test_to_yahoo_ticker_appends_mapped_suffix() -> None:
    assert to_yahoo_ticker("ISAC", "LN") == "ISAC.L"
    assert to_yahoo_ticker("ATR", "PW") == "ATR.WA"


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
