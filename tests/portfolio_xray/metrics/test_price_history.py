import sys
import types
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from fin_ai_lab.portfolio_xray.metrics.price_history import (  # noqa: E402
    fetch_price_history,
    price_change_ratio,
)


def _install_fake_yfinance(
    monkeypatch: pytest.MonkeyPatch, history_df, call_count: dict | None = None
) -> None:
    fake_module = types.ModuleType("yfinance")

    class FakeTicker:
        def __init__(self, ticker: str) -> None:
            self._ticker = ticker

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
