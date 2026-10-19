from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from portfolio_xray._fixtures import (  # noqa: E402
    SYNTH_A_ISIN,
    SYNTH_B_ISIN,
    build_synthetic_bossa_financial_csv,
    build_synthetic_xtb_workbook,
)

from fin_ai_lab.portfolio_webapp.api import create_app  # noqa: E402
from fin_ai_lab.portfolio_xray.identification.openfigi import Identification, Listing  # noqa: E402

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
D = Decimal
TODAY = date(2026, 1, 10)
DAY = datetime(2026, 1, 2, 10, 0, 0)
LATER_DAY = datetime(2026, 1, 6, 10, 0, 0)


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


class _ListingsOpenFigi:
    """Leaves every held position ambiguous, as the import's lookup leaves a
    US stock in a Bossa account, and lists canned listings per ISIN for the
    ledger's own lookup (#277)."""

    def __init__(self, listings: dict[str, list[Listing]]) -> None:
        self._listings = listings

    async def resolve_by_isin(self, isin: str, currency: str | None, broker_market=None):
        return Identification(status="ambiguous")

    async def listings_by_isin(self, jobs: list[tuple[str, str | None]]) -> list[list[Listing]]:
        return [self._listings.get(isin, []) for isin, _ in jobs]


def _client(
    tmp_path: Path, fx: _FakeFx | None = None, openfigi: _ListingsOpenFigi | None = None
) -> TestClient:
    app = create_app(
        db_path=tmp_path / "test.duckdb",
        openfigi_client_factory=lambda: openfigi,
        price_ratio_fetcher=lambda ticker, since: None,
        quote_currency_fetcher=lambda ticker: None,
        daily_closes_fetcher=lambda ticker, start, refresh: None,
        fx_client_factory=lambda: fx or _FakeFx(),
        today_provider=lambda: TODAY,
    )
    return TestClient(app)


def _create_portfolio(client: TestClient, name: str, broker: str) -> str:
    response = client.post(
        "/api/portfolios", json={"name": name, "broker": broker, "account_type": "regular"}
    )
    return response.json()["id"]


def _import_xtb(client: TestClient, portfolio_id: str, operations, account_currency="PLN"):
    workbook = build_synthetic_xtb_workbook(
        cash_operations=operations, account_currency=account_currency
    )
    response = client.post(
        f"/api/portfolios/{portfolio_id}/import",
        files={"file": ("positions.xlsx", workbook, XLSX_CONTENT_TYPE)},
        data={"valuation_date": "2026-01-05"},
    )
    assert response.status_code == 201, response.text


def _import_bossa(client: TestClient, portfolio_id: str, content: bytes) -> None:
    response = client.post(
        f"/api/portfolios/{portfolio_id}/import/bossa",
        files={"file": ("hf.csv", content, "text/csv")},
        data={"valuation_date": "2026-01-06"},
    )
    assert response.status_code == 201, response.text


XTB_OPERATIONS = [
    ("Stock purchase", "Atrem", DAY, -500.0, "1", "ATR.PL", ""),
    ("Dividend", "Atrem", DAY, 10.0, "2", "ATR.PL", "ATR.PL PLN 1.00/ SHR"),
    ("Withholding tax", "Atrem", DAY, -1.9, "3", "ATR.PL", "ATR.PL PLN WHT 19%"),
    ("Dividend", "Atrem", LATER_DAY, 5.0, "4", "ATR.PL", "ATR.PL PLN 0.50/ SHR"),
]


def test_xtb_dividends_are_linked_and_add_up_to_the_investment_result(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        portfolio_id = _create_portfolio(client, "XTB", "xtb")
        _import_xtb(client, portfolio_id, XTB_OPERATIONS)

        history = client.get(f"/api/portfolios/{portfolio_id}/dividends/history").json()
        valuation = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    assert history["total"] == "13.10"  # 10 - 1.90 withheld + 5
    assert history["total"] == valuation["portfolios"][0]["investment"]["dividends"]
    assert history["current_year"] == "13.10"
    assert [(y["year"], y["total"]) for y in history["years"]] == [(2026, "13.10")]
    (instrument,) = history["instruments"]
    assert instrument["instrument_key"] == "xtb:ATR.PL"
    assert (instrument["name"], instrument["payment_count"]) == ("Atrem", 2)
    assert [(p["paid_on"], p["amount"]) for p in history["payments"]] == [
        ("2026-01-06", "5.00000000"),
        ("2026-01-02", "8.10000000"),
    ]
    assert history["warnings"] == []


def test_bossa_dividend_is_linked_by_the_name_its_trades_use(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        portfolio_id = _create_portfolio(client, "IKE", "bossa")
        _import_bossa(client, portfolio_id, build_synthetic_bossa_financial_csv())

        history = client.get(f"/api/portfolios/{portfolio_id}/dividends/history").json()

    (instrument,) = history["instruments"]
    assert (instrument["instrument_key"], instrument["name"], instrument["total"]) == (
        SYNTH_A_ISIN,
        "SYNTHA",
        "12.50",
    )


def test_unlinked_dividend_still_counts_and_is_named_in_a_warning(tmp_path: Path) -> None:
    content = build_synthetic_bossa_financial_csv(
        ["2026-01-04;Wypłata dywidendy MURAPOL;;7,00;PLN"]
    )
    with _client(tmp_path) as client:
        portfolio_id = _create_portfolio(client, "IKE", "bossa")
        _import_bossa(client, portfolio_id, content)

        history = client.get(f"/api/portfolios/{portfolio_id}/dividends/history").json()

    assert history["total"] == "19.50"
    unlinked = [i for i in history["instruments"] if i["instrument_key"] is None]
    assert [(i["name"], i["total"]) for i in unlinked] == [("MURAPOL", "7.00")]
    assert any("MURAPOL" in warning for warning in history["warnings"])


USD_AT_4 = {"USD": {"2026-01-02": "4.00"}}


def _bossa_ticker_history(tmp_path: Path, listings: dict[str, list[Listing]], code: str) -> dict:
    # #269: Bossa names a foreign company in the dividend title only by its
    # ticker, which neither the held ambiguous SYNTHA nor the sold SYNTHB
    # carries as a position -- only the ledger's listing does.
    content = build_synthetic_bossa_financial_csv(
        [f"2026-01-04;Wypłata dywidendy netto {code} 85% USD;;2,00;USD"]
    )
    with _client(tmp_path, _FakeFx(USD_AT_4), _ListingsOpenFigi(listings)) as client:
        portfolio_id = _create_portfolio(client, "IKE", "bossa")
        _import_bossa(client, portfolio_id, content)
        return client.get(f"/api/portfolios/{portfolio_id}/dividends/history").json()


def test_bossa_dividend_of_a_sold_company_is_linked_by_its_listing_ticker(
    tmp_path: Path,
) -> None:
    listings = {SYNTH_B_ISIN: [Listing(ticker="SYB", exchange_code="PW")]}

    history = _bossa_ticker_history(tmp_path, listings, "SYB")

    by_key = {i["instrument_key"]: (i["name"], i["total"]) for i in history["instruments"]}
    assert by_key[SYNTH_B_ISIN] == ("SYNTHB", "8.00")  # 2 USD at 4.00
    assert history["warnings"] == []


def test_bossa_dividend_of_an_ambiguous_held_company_is_linked_by_its_listing_ticker(
    tmp_path: Path,
) -> None:
    listings = {SYNTH_A_ISIN: [Listing(ticker="SYA", exchange_code="PW")]}

    history = _bossa_ticker_history(tmp_path, listings, "SYA")

    # One row with the payment the title names by the trades' own name.
    (instrument,) = history["instruments"]
    assert (instrument["instrument_key"], instrument["payment_count"]) == (SYNTH_A_ISIN, 2)
    assert instrument["total"] == "20.50"  # 12.50 PLN + 2 USD at 4.00
    assert history["warnings"] == []


def test_listing_ticker_two_isins_share_links_neither(tmp_path: Path) -> None:
    shared = [Listing(ticker="SYX", exchange_code="PW")]

    history = _bossa_ticker_history(tmp_path, {SYNTH_A_ISIN: shared, SYNTH_B_ISIN: shared}, "SYX")

    unlinked = [i for i in history["instruments"] if i["instrument_key"] is None]
    assert [(i["name"], i["total"]) for i in unlinked] == [("SYX", "8.00")]
    assert any("SYX" in warning for warning in history["warnings"])


def test_all_portfolios_history_names_the_portfolio_of_each_payment(tmp_path: Path) -> None:
    fx = _FakeFx({"USD": {"2026-01-02": "4.00"}})
    with _client(tmp_path, fx) as client:
        xtb_id = _create_portfolio(client, "XTB USD", "xtb")
        _import_xtb(client, xtb_id, XTB_OPERATIONS[:2], account_currency="USD")
        bossa_id = _create_portfolio(client, "IKE", "bossa")
        _import_bossa(client, bossa_id, build_synthetic_bossa_financial_csv())

        history = client.get("/api/dividends/history").json()

    assert history["total"] == "52.50"  # 10 USD at 4.00 + 12.50 PLN
    by_portfolio = {
        p["portfolio_name"]: (p["fx_rate"], p["amount_base"]) for p in history["payments"]
    }
    assert by_portfolio == {"XTB USD": ("4.0000", "40.00"), "IKE": ("1.0000", "12.50")}


def test_missing_nbp_rate_leaves_the_currency_out_of_the_sums(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        portfolio_id = _create_portfolio(client, "XTB USD", "xtb")
        _import_xtb(client, portfolio_id, XTB_OPERATIONS[:2], account_currency="USD")

        history = client.get(f"/api/portfolios/{portfolio_id}/dividends/history").json()

    assert history["total"] == "0.00"
    (payment,) = history["payments"]
    assert (payment["fx_rate"], payment["amount_base"]) == (None, None)
    assert any("USD" in warning for warning in history["warnings"])


def test_reimport_fills_in_the_ticker_of_rows_stored_without_it(tmp_path: Path) -> None:
    without_ticker = [operation[:5] for operation in XTB_OPERATIONS]
    with _client(tmp_path) as client:
        portfolio_id = _create_portfolio(client, "XTB", "xtb")
        _import_xtb(client, portfolio_id, without_ticker)
        before = client.get(f"/api/portfolios/{portfolio_id}/dividends/history").json()

        _import_xtb(client, portfolio_id, XTB_OPERATIONS)
        after = client.get(f"/api/portfolios/{portfolio_id}/dividends/history").json()

    assert [i["instrument_key"] for i in before["instruments"]] == [None]
    assert [i["instrument_key"] for i in after["instruments"]] == ["xtb:ATR.PL"]
    assert after["total"] == before["total"]  # nothing counted twice


def test_portfolio_without_dividends_has_an_empty_history(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        portfolio_id = _create_portfolio(client, "XTB", "xtb")

        history = client.get(f"/api/portfolios/{portfolio_id}/dividends/history").json()

    assert history["total"] == "0.00"
    assert history["instruments"] == []
    assert history["payments"] == []


def test_unknown_portfolio_is_404(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get(f"/api/portfolios/{uuid4()}/dividends/history")

    assert response.status_code == 404
