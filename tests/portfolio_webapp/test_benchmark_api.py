from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from fin_ai_lab.portfolio_webapp.api import create_app  # noqa: E402

D = Decimal


class _Closes:
    """Canned dividend-adjusted closes per ticker; records every lookup."""

    def __init__(self, by_ticker: dict[str, dict[str, str]], fail: bool = False) -> None:
        self._by_ticker = {
            ticker: {date.fromisoformat(d): D(v) for d, v in closes.items()}
            for ticker, closes in by_ticker.items()
        }
        self._fail = fail
        self.calls: list[tuple[str, date, bool]] = []

    def __call__(self, ticker: str, start: date, refresh: bool) -> dict[date, Decimal] | None:
        self.calls.append((ticker, start, refresh))
        if self._fail:
            raise ConnectionError("blocked")
        return self._by_ticker.get(ticker)


class _FakeFx:
    def __init__(self, series: dict[str, dict[str, str]]) -> None:
        self._series = {
            code: {date.fromisoformat(d): D(v) for d, v in rates.items()}
            for code, rates in series.items()
        }

    async def mid_rate_series(self, currency: str, start: date, end: date) -> dict:
        if currency not in self._series:
            raise LookupError(currency)
        return self._series[currency]


def _client(
    tmp_path: Path,
    closes: _Closes,
    currencies: dict[str, str],
    fx: dict[str, dict[str, str]] | None = None,
) -> TestClient:
    app = create_app(
        db_path=tmp_path / "test.duckdb",
        openfigi_client_factory=lambda: None,
        quote_currency_fetcher=currencies.get,
        benchmark_closes_fetcher=closes,
        fx_client_factory=lambda: _FakeFx(fx or {}),
        today_provider=lambda: date(2026, 1, 6),
    )
    return TestClient(app)


def test_built_in_list_has_wig20_through_its_total_return_fund(tmp_path: Path) -> None:
    with _client(tmp_path, _Closes({}), {}) as client:
        body = client.get("/api/benchmarks").json()

    by_id = {item["id"]: item for item in body}
    assert by_id["wig20"]["ticker"] == "ETFBW20TR.WA"
    assert by_id["sp500"]["ticker"] == "^SP500TR"


def test_benchmark_comes_on_the_valuation_day_axis_in_pln(tmp_path: Path) -> None:
    closes = _Closes({"^SP500TR": {"2026-01-02": "100", "2026-01-05": "110"}})
    fx = {"USD": {"2026-01-02": "4.00", "2026-01-05": "4.00"}}
    with _client(tmp_path, closes, {"^SP500TR": "USD"}, fx) as client:
        body = client.get(
            "/api/benchmark", params={"ticker": "^sp500tr", "start": "2026-01-03"}
        ).json()

    assert body["ticker"] == "^SP500TR"
    assert body["label"] == "S&P 500"
    assert body["quote_currency"] == "USD"
    assert body["dates"] == ["2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06"]
    assert body["values"] == ["1.000000", "1.000000", "1.100000", "1.100000"]
    assert body["first_price_date"] == "2026-01-03"
    assert body["prices_as_of"] == "2026-01-05"
    # Fetched from the first of the month before the window, for the cache.
    assert closes.calls == [("^SP500TR", date(2025, 12, 1), False)]


def test_custom_ticker_is_labelled_with_itself(tmp_path: Path) -> None:
    closes = _Closes({"PKO.WA": {"2026-01-05": "50", "2026-01-06": "51"}})
    with _client(tmp_path, closes, {"PKO.WA": "PLN"}) as client:
        body = client.get(
            "/api/benchmark", params={"ticker": "pko.wa", "start": "2026-01-05", "refresh": True}
        ).json()

    assert body["label"] == "PKO.WA"
    assert body["note"] is None
    assert body["values"] == ["1.000000", "1.020000"]
    assert closes.calls[0][2] is True


def test_invalid_ticker_is_rejected_before_yahoo(tmp_path: Path) -> None:
    closes = _Closes({})
    with _client(tmp_path, closes, {}) as client:
        response = client.get("/api/benchmark", params={"ticker": "../x", "start": "2026-01-05"})

    assert response.status_code == 422
    assert closes.calls == []


def test_unknown_ticker_is_404(tmp_path: Path) -> None:
    with _client(tmp_path, _Closes({}), {}) as client:
        response = client.get("/api/benchmark", params={"ticker": "NOPE", "start": "2026-01-05"})

    assert response.status_code == 404
    assert "NOPE" in response.json()["detail"]


def test_unknown_ticker_is_404_even_when_the_currency_lookup_raises(tmp_path: Path) -> None:
    # yfinance's fast_info raises KeyError('currency') for a symbol Yahoo
    # does not know -- never asked once there are no closes anyway.
    asked: list[str] = []

    def currency_lookup(ticker: str) -> str | None:
        asked.append(ticker)
        raise KeyError("currency")

    closes = _Closes({"ODD": {"2026-01-05": "10"}})
    app = create_app(
        db_path=tmp_path / "test.duckdb",
        openfigi_client_factory=lambda: None,
        quote_currency_fetcher=currency_lookup,
        benchmark_closes_fetcher=closes,
        fx_client_factory=lambda: _FakeFx({}),
        today_provider=lambda: date(2026, 1, 6),
    )
    with TestClient(app) as client:
        unknown = client.get("/api/benchmark", params={"ticker": "NOPE", "start": "2026-01-05"})
        odd = client.get("/api/benchmark", params={"ticker": "ODD", "start": "2026-01-05"})

    assert unknown.status_code == 404
    assert odd.status_code == 404
    assert asked == ["ODD"]


def test_yahoo_failure_is_502(tmp_path: Path) -> None:
    with _client(tmp_path, _Closes({}, fail=True), {}) as client:
        response = client.get("/api/benchmark", params={"ticker": "QQQ", "start": "2026-01-05"})

    assert response.status_code == 502


def test_currency_without_nbp_rate_is_422(tmp_path: Path) -> None:
    closes = _Closes({"XYZ.F": {"2026-01-05": "10"}})
    with _client(tmp_path, closes, {"XYZ.F": "XYZ"}) as client:
        response = client.get("/api/benchmark", params={"ticker": "XYZ.F", "start": "2026-01-05"})

    assert response.status_code == 422
    assert "XYZ" in response.json()["detail"]
