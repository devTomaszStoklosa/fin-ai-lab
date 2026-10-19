from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from portfolio_xray._fixtures import build_synthetic_xtb_workbook  # noqa: E402

from fin_ai_lab.portfolio_webapp.api import create_app  # noqa: E402

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
D = Decimal
TODAY = date(2026, 10, 13)


class _FakeFx:
    def __init__(self, series: dict[str, dict[str, str]] | None = None) -> None:
        self._series = {
            code: {date.fromisoformat(d): D(v) for d, v in rates.items()}
            for code, rates in (series or {}).items()
        }

    async def mid_rate_series(self, currency: str, start: date, end: date) -> dict:
        if currency not in self._series:
            raise LookupError(currency)
        return self._series[currency]


class _Yahoo:
    """Canned Yahoo answers per ticker: closes (None = unknown ticker),
    per-share dividends and the quote currency."""

    def __init__(self, listings: dict[str, tuple[str | None, list[tuple[str, str]], str]]) -> None:
        self._listings = listings

    def closes(self, ticker: str, start: date, refresh: bool) -> dict[date, Decimal] | None:
        listing = self._listings.get(ticker)
        if listing is None or listing[0] is None:
            return None
        return {date(2026, 10, 9): D(listing[0])}

    def dividends(self, ticker: str) -> list[tuple[date, Decimal]]:
        listing = self._listings.get(ticker)
        return [(date.fromisoformat(d), D(a)) for d, a in listing[1]] if listing else []

    def currency(self, ticker: str) -> str | None:
        listing = self._listings.get(ticker)
        return listing[2] if listing else None


def _client(tmp_path: Path, yahoo: _Yahoo, fx: _FakeFx | None = None) -> TestClient:
    app = create_app(
        db_path=tmp_path / "test.duckdb",
        openfigi_client_factory=lambda: None,
        price_ratio_fetcher=lambda ticker, since: None,
        quote_currency_fetcher=yahoo.currency,
        daily_closes_fetcher=yahoo.closes,
        dividends_fetcher=yahoo.dividends,
        fx_client_factory=lambda: fx or _FakeFx(),
        today_provider=lambda: TODAY,
    )
    return TestClient(app)


def _xtb_portfolio(client: TestClient, operations=None, account_type: str = "regular") -> str:
    portfolio_id = client.post(
        "/api/portfolios", json={"name": "XTB", "broker": "xtb", "account_type": account_type}
    ).json()["id"]
    # Holds ISAC.UK (6, Yahoo ISAC.L) and ATR.PL (1, Yahoo ATR.WA).
    workbook = build_synthetic_xtb_workbook(cash_operations=operations)
    response = client.post(
        f"/api/portfolios/{portfolio_id}/import",
        files={"file": ("positions.xlsx", workbook, XLSX_CONTENT_TYPE)},
        data={"valuation_date": "2026-10-01"},
    )
    assert response.status_code == 201, response.text
    return portfolio_id


def _forecast(client: TestClient, portfolio_id: str) -> dict:
    response = client.get(f"/api/portfolios/{portfolio_id}/dividends/forecast")
    assert response.status_code == 200, response.text
    return response.json()


def test_estimate_for_the_next_calendar_year_from_yahoo(tmp_path: Path) -> None:
    yahoo = _Yahoo(
        {
            "ATR.WA": ("12", [("2025-08-08", "1.69"), ("2026-08-07", "2.16")], "PLN"),
            "ISAC.L": ("100", [], "USD"),  # pays nothing
        }
    )
    with _client(tmp_path, yahoo) as client:
        body = _forecast(client, _xtb_portfolio(client))

    assert body["year"] == 2027
    assert body["total"] == "2.16"  # 1 share x 2.16 PLN; the 2025 payout is more than a year ago
    assert body["months"][7] == "2.16"  # August
    atrem, isac = body["rows"]
    assert (atrem["instrument_key"], atrem["source"], atrem["per_share"]) == (
        "xtb:ATR.PL",
        "yahoo",
        "2.1600",
    )
    assert atrem["yield_pct"] == "18.0"  # 2.16 / 12
    assert (isac["source"], isac["estimate"]) == ("yahoo", "0.00")
    assert body["warnings"] == []


def test_unknown_to_yahoo_uses_the_per_share_amounts_xtb_stated(tmp_path: Path) -> None:
    operations = [
        (
            "Dividend",
            "Atrem",
            datetime(2026, 9, 22, 11, 0),
            0.72,
            "1",
            "ATR.PL",
            "ATR.PL PLN 0.72/ SHR",
        ),
        (
            "Withholding tax",
            "Atrem",
            datetime(2026, 9, 22, 11, 0),
            -0.14,
            "2",
            "ATR.PL",
            "ATR.PL PLN WHT 19%",
        ),
    ]
    with _client(tmp_path, _Yahoo({})) as client:
        body = _forecast(client, _xtb_portfolio(client, operations))

    atrem = next(row for row in body["rows"] if row["instrument_key"] == "xtb:ATR.PL")
    assert (atrem["source"], atrem["estimate"], atrem["yield_pct"]) == ("history", "0.72", None)
    assert body["months"][8] == "0.72"  # September, gross: the tax row states no amount
    assert any("MSCI ACWI" in warning for warning in body["warnings"])  # no data at all


def test_yahoo_disagreeing_with_the_statement_is_flagged(tmp_path: Path) -> None:
    # Yahoo lists one 2.16 payout, the account was paid 0.72 three times.
    operations = [
        (
            "Dividend",
            "Atrem",
            datetime(2026, m, 18, 10, 0),
            0.72,
            str(m),
            "ATR.PL",
            "ATR.PL PLN 0.72/ SHR",
        )
        for m in (7, 8, 9)
    ]
    yahoo = _Yahoo({"ATR.WA": ("12", [("2026-08-07", "2.16")], "PLN")})
    with _client(tmp_path, yahoo) as client:
        body = _forecast(client, _xtb_portfolio(client, operations))

    atrem = next(row for row in body["rows"] if row["instrument_key"] == "xtb:ATR.PL")
    assert atrem["mismatch"] is True
    assert atrem["estimate"] == "2.16"  # still Yahoo's amount
    assert any("Atrem" in warning and "ratach" in warning for warning in body["warnings"])


def test_foreign_dividends_are_converted_at_todays_nbp_rate(tmp_path: Path) -> None:
    yahoo = _Yahoo({"ISAC.L": ("50", [("2026-06-18", "0.50")], "USD")})
    fx = _FakeFx({"USD": {"2026-10-12": "3.70", "2026-10-13": "3.75"}})
    with _client(tmp_path, yahoo, fx) as client:
        body = _forecast(client, _xtb_portfolio(client))

    assert body["months"][5] == "11.25"  # 6 x 0.50 USD x 3.75, in June


def test_missing_nbp_rate_is_a_warning_not_an_error(tmp_path: Path) -> None:
    yahoo = _Yahoo({"ISAC.L": ("50", [("2026-06-18", "0.50")], "USD")})
    with _client(tmp_path, yahoo) as client:
        body = _forecast(client, _xtb_portfolio(client))

    assert body["total"] == "0.00"
    assert any("USD" in warning for warning in body["warnings"])


def test_a_yahoo_failure_degrades_to_no_data(tmp_path: Path) -> None:
    def failing(ticker: str) -> list:
        raise RuntimeError("blocked")

    yahoo = _Yahoo({"ATR.WA": ("12", [("2026-08-07", "2.16")], "PLN")})
    app = create_app(
        db_path=tmp_path / "test.duckdb",
        openfigi_client_factory=lambda: None,
        price_ratio_fetcher=lambda ticker, since: None,
        quote_currency_fetcher=yahoo.currency,
        daily_closes_fetcher=yahoo.closes,
        dividends_fetcher=failing,
        fx_client_factory=_FakeFx,
        today_provider=lambda: TODAY,
    )
    with TestClient(app) as client:
        body = _forecast(client, _xtb_portfolio(client))

    assert {row["source"] for row in body["rows"]} == {"none"}


def test_all_portfolios_and_unknown_portfolio(tmp_path: Path) -> None:
    yahoo = _Yahoo({"ATR.WA": ("12", [("2026-08-07", "2.16")], "PLN")})
    with _client(tmp_path, yahoo) as client:
        _xtb_portfolio(client)
        everything = client.get("/api/dividends/forecast").json()
        missing = client.get(f"/api/portfolios/{uuid4()}/dividends/forecast")

    assert everything["total"] == "2.16"
    assert missing.status_code == 404


# #267: Atrem (PL) pays 2.16 PLN on 1 share, MSCI ACWI (London, "UK") pays
# 0.50 USD on 6 shares at 3.75.
TAXED_YAHOO = {
    "ATR.WA": ("12", [("2026-08-07", "2.16")], "PLN"),
    "ISAC.L": ("50", [("2026-06-18", "0.50")], "USD"),
}
TAXED_FX = {"USD": {"2026-10-13": "3.75"}}


def _rows(body: dict) -> dict[str, dict]:
    return {row["instrument_key"]: row for row in body["rows"]}


def test_regular_account_withholds_19_percent_and_owes_the_top_up_abroad(tmp_path: Path) -> None:
    with _client(tmp_path, _Yahoo(TAXED_YAHOO), _FakeFx(TAXED_FX)) as client:
        body = _forecast(client, _xtb_portfolio(client))

    rows = _rows(body)
    atrem, acwi = rows["xtb:ATR.PL"], rows["xtb:ISAC.UK"]
    assert (atrem["credited"], atrem["withholding_pct"], atrem["tax_basis"]) == (
        "1.75",  # 2.16 less 19% at the broker
        "19.0",
        "rule",
    )
    # UK withholds nothing; the whole 19% is due in the tax return.
    assert (acwi["credited"], acwi["top_up"], acwi["withholding_pct"]) == ("11.25", "2.14", "0.0")
    assert body["total"] == "13.41"
    assert body["total_credited"] == "13.00"
    assert body["total_top_up"] == "2.14"
    assert body["months_credited"][5] == "11.25"  # June


def test_the_rate_from_the_accounts_own_statement_wins(tmp_path: Path) -> None:
    operations = [
        ("Dividend", "MSCI ACWI", datetime(2026, 6, 25, 9, 0), 3.0, "1", "ISAC.UK", ""),
        (
            "Withholding tax",
            "MSCI ACWI",
            datetime(2026, 6, 25, 9, 0),
            -0.45,
            "2",
            "ISAC.UK",
            "ISAC.UK USD WHT 15%",
        ),
    ]
    with _client(tmp_path, _Yahoo(TAXED_YAHOO), _FakeFx(TAXED_FX)) as client:
        body = _forecast(client, _xtb_portfolio(client, operations))

    acwi = _rows(body)["xtb:ISAC.UK"]
    assert (acwi["withholding_pct"], acwi["tax_basis"]) == ("15.0", "statement")
    assert (acwi["credited"], acwi["top_up"]) == ("9.56", "0.45")


def test_ike_pays_nothing_on_polish_dividends_and_no_top_up(tmp_path: Path) -> None:
    with _client(tmp_path, _Yahoo(TAXED_YAHOO), _FakeFx(TAXED_FX)) as client:
        body = _forecast(client, _xtb_portfolio(client, account_type="ike"))

    assert _rows(body)["xtb:ATR.PL"]["credited"] == "2.16"
    assert body["total_credited"] == body["total"] == "13.41"
    assert body["total_top_up"] == "0.00"


def test_unknown_account_type_keeps_the_gross_amount_with_a_warning(tmp_path: Path) -> None:
    with _client(tmp_path, _Yahoo(TAXED_YAHOO), _FakeFx(TAXED_FX)) as client:
        body = _forecast(client, _xtb_portfolio(client, account_type="other"))

    assert body["total_credited"] == body["total"]
    assert {row["tax_basis"] for row in body["rows"]} == {"unknown"}
    assert any("Nieznana stawka podatku" in warning for warning in body["warnings"])
