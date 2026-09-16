import sys
import types
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from fin_ai_lab.portfolio_xray.metrics.price_history import fetch_price_history  # noqa: E402


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
