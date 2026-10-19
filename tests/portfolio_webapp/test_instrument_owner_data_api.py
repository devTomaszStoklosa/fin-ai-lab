from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from portfolio_xray._fixtures import build_synthetic_xtb_workbook  # noqa: E402

from fin_ai_lab.portfolio_webapp.api import create_app  # noqa: E402

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# Bought for PLN on Bossa, listed in USD (#279's case); with no OpenFIGI in
# these tests nothing resolves it, so it has no symbol and no currency.
SEDG_ISIN = "US83417M1045"
LEDGER = (
    "data;papier;isin;ilość;-;cena;wartość;prowizja;po prowizji;waluta\r\n"
    f"02.01.2026 10:00:00;SOLAREDGE;{SEDG_ISIN};6;K;400,00;2400,00;5,00;2405,00;PLN\r\n"
).encode("cp1250")
USD = {"2026-01-02": "4.00", "2026-01-06": "4.20"}


class _Closes:
    def __init__(self, by_ticker: dict[str, dict[str, str]] | None = None) -> None:
        self._by_ticker = {
            ticker: {date.fromisoformat(d): Decimal(v) for d, v in closes.items()}
            for ticker, closes in (by_ticker or {}).items()
        }
        self.tickers: list[str] = []
        self.fail = False

    def __call__(self, ticker: str, start: date, refresh: bool) -> dict[date, Decimal] | None:
        if self.fail:
            raise ConnectionError("blocked")
        self.tickers.append(ticker)
        return self._by_ticker.get(ticker)


class _FakeFx:
    def __init__(self, series: dict[str, dict[str, str]]) -> None:
        self._series = {
            code: {date.fromisoformat(d): Decimal(v) for d, v in rates.items()}
            for code, rates in series.items()
        }

    async def mid_rate_series(self, currency: str, start: date, end: date) -> dict:
        if currency not in self._series:
            raise LookupError(currency)
        return self._series[currency]


def _client(tmp_path: Path, closes: _Closes, quote_currencies: dict[str, str] | None = None):
    app = create_app(
        db_path=tmp_path / "test.duckdb",
        openfigi_client_factory=lambda: None,
        price_ratio_fetcher=lambda ticker, since: None,
        quote_currency_fetcher=lambda ticker: (quote_currencies or {}).get(ticker),
        daily_closes_fetcher=closes,
        fx_client_factory=lambda: _FakeFx({"USD": USD}),
        today_provider=lambda: date(2026, 1, 6),
    )
    return TestClient(app)


def _import_bossa(client: TestClient) -> str:
    portfolio_id = client.post(
        "/api/portfolios", json={"name": "IKE", "broker": "bossa", "account_type": "ike"}
    ).json()["id"]
    response = client.post(
        f"/api/portfolios/{portfolio_id}/import/bossa",
        files={"file": ("hisPW.csv", LEDGER, "text/csv")},
        data={"valuation_date": "2026-01-05"},
    )
    assert response.status_code == 201, response.text
    return portfolio_id


def _save(client: TestClient, key: str, yahoo_ticker: str | None, quote_currency: str | None):
    return client.post(
        "/api/instruments/owner-data",
        json={"key": key, "yahoo_ticker": yahoo_ticker, "quote_currency": quote_currency},
    )


def _instrument(body: dict, key: str) -> dict:
    return next(i for i in body["instruments"] if i["key"] == key)


def test_owner_symbol_and_currency_price_an_instrument_the_import_could_not(
    tmp_path: Path,
) -> None:
    closes = _Closes({"SEDG": {"2026-01-02": "100", "2026-01-06": "110"}})
    with _client(tmp_path, closes) as client:
        _import_bossa(client)
        before = _instrument(client.get("/api/instruments").json(), SEDG_ISIN)
        assert (before["yahoo_ticker"], before["quote_currency"]) == (None, None)
        assert before["has_quotes"] is False
        assert client.get("/api/valuation").json()["total_value"] == "2400.00"

        body = _save(client, SEDG_ISIN, " sedg ", "USD").json()

        after = _instrument(body, SEDG_ISIN)
        assert (after["owner_yahoo_ticker"], after["owner_quote_currency"]) == ("SEDG", "USD")
        assert (after["yahoo_ticker"], after["quote_currency"]) == ("SEDG", "USD")
        assert after["has_quotes"] is True
        # Right away, no re-import: 6 x 400 PLN at the trade, price +10%,
        # USD/PLN +5%.
        assert client.get("/api/valuation").json()["total_value"] == "2772.00"


def test_symbol_without_currency_takes_yahoos(tmp_path: Path) -> None:
    closes = _Closes({"SEDG": {"2026-01-06": "110"}})
    with _client(tmp_path, closes, {"SEDG": "USD"}) as client:
        _import_bossa(client)

        body = _save(client, SEDG_ISIN, "SEDG", None).json()

    assert _instrument(body, SEDG_ISIN)["owner_quote_currency"] == "USD"


def test_currency_alone_is_stored_without_asking_yahoo(tmp_path: Path) -> None:
    closes = _Closes()
    with _client(tmp_path, closes) as client:
        _import_bossa(client)
        closes.tickers.clear()

        body = _save(client, SEDG_ISIN, None, "USD").json()

    instrument = _instrument(body, SEDG_ISIN)
    assert (instrument["owner_yahoo_ticker"], instrument["owner_quote_currency"]) == (None, "USD")
    assert closes.tickers == []  # the valuation had nothing to look up either


def test_clearing_both_fields_removes_the_entry(tmp_path: Path) -> None:
    closes = _Closes({"SEDG": {"2026-01-02": "100", "2026-01-06": "110"}})
    with _client(tmp_path, closes) as client:
        _import_bossa(client)
        _save(client, SEDG_ISIN, "SEDG", "USD")

        body = _save(client, SEDG_ISIN, "", None).json()

        instrument = _instrument(body, SEDG_ISIN)
        assert (instrument["owner_yahoo_ticker"], instrument["owner_quote_currency"]) == (
            None,
            None,
        )
        assert client.get("/api/valuation").json()["total_value"] == "2400.00"


def test_symbol_yahoo_does_not_know_is_refused(tmp_path: Path) -> None:
    with _client(tmp_path, _Closes()) as client:
        _import_bossa(client)

        response = _save(client, SEDG_ISIN, "NOPE.L", "USD")

        assert response.status_code == 422
        assert "Yahoo nie zna symbolu NOPE.L" in response.json()["detail"]
        stored = _instrument(client.get("/api/instruments").json(), SEDG_ISIN)
        assert stored["owner_quote_currency"] is None  # nothing half-saved


def test_yahoo_down_is_a_readable_error(tmp_path: Path) -> None:
    closes = _Closes()
    with _client(tmp_path, closes) as client:
        _import_bossa(client)
        closes.fail = True

        response = _save(client, SEDG_ISIN, "SEDG", "USD")

    assert response.status_code == 502


def test_owner_data_requests_are_validated(tmp_path: Path) -> None:
    with _client(tmp_path, _Closes()) as client:
        portfolio_id = _import_bossa(client)
        manual = client.post(
            f"/api/portfolios/{portfolio_id}/positions",
            json={"instrument_name": "Obligacje", "asset_class": "bond",
                  "quantity": "10", "avg_cost": "100"},
        ).json()  # fmt: skip

        assert _save(client, SEDG_ISIN, "SE DG", None).status_code == 422
        assert _save(client, SEDG_ISIN, None, "CHF").status_code == 422
        assert _save(client, "xtb:NOPE", None, "USD").status_code == 422
        assert _save(client, f"manual:{manual['id']}", None, "USD").status_code == 422


def test_owner_currency_wins_over_the_one_an_xtb_symbol_implies(tmp_path: Path) -> None:
    # ATR.PL's suffix implies PLN; the owner's answer counts instead.
    closes = _Closes({"ATR.WA": {"2026-01-05": "10", "2026-01-06": "10"}})
    with _client(tmp_path, closes) as client:
        portfolio_id = client.post(
            "/api/portfolios", json={"name": "XTB", "broker": "xtb", "account_type": "regular"}
        ).json()["id"]
        client.post(
            f"/api/portfolios/{portfolio_id}/import",
            files={"file": ("p.xlsx", build_synthetic_xtb_workbook(), XLSX_CONTENT_TYPE)},
            data={"valuation_date": "2026-01-05"},
        )

        body = _save(client, "xtb:ATR.PL", None, "USD").json()

        assert _instrument(body, "xtb:ATR.PL")["quote_currency"] == "USD"
        position = next(
            p
            for p in client.get(f"/api/portfolios/{portfolio_id}/valuation").json()["positions"]
            if p["symbol"] == "ATR.PL"
        )
        assert position["quote_currency"] == "USD"
        # Same price, USD/PLN 4.00 (on or before the import) -> 4.20: +5%.
        assert position["value"] == "55.97"
