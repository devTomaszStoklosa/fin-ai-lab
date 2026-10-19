from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from portfolio_xray._fixtures import (  # noqa: E402
    SYNTH_A_ISIN,
    SYNTH_B_ISIN,
    bossa_settlement_row,
    build_synthetic_bossa_csv,
    build_synthetic_bossa_financial_csv,
    build_synthetic_xtb_workbook,
)

from fin_ai_lab.portfolio_webapp.api import create_app  # noqa: E402
from fin_ai_lab.portfolio_xray.identification.openfigi import Identification, Listing  # noqa: E402

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
D = Decimal


class _Closes:
    """Canned daily closes per Yahoo ticker; records every lookup."""

    def __init__(self, by_ticker: dict[str, dict[str, str]] | None = None) -> None:
        self._by_ticker = {
            ticker: {date.fromisoformat(d): D(v) for d, v in closes.items()}
            for ticker, closes in (by_ticker or {}).items()
        }
        self.calls: list[tuple[str, date, bool]] = []

    def __call__(self, ticker: str, start: date, refresh: bool) -> dict[date, Decimal] | None:
        self.calls.append((ticker, start, refresh))
        return self._by_ticker.get(ticker)


class _FakeFx:
    def __init__(self, series: dict[str, dict[str, str]] | None = None) -> None:
        self._series = {
            code: {date.fromisoformat(d): D(v) for d, v in rates.items()}
            for code, rates in (series or {}).items()
        }
        self.requested: list[str] = []

    async def mid_rate_series(self, currency: str, start: date, end: date) -> dict:
        self.requested.append(currency)
        if currency not in self._series:
            raise LookupError(currency)
        return self._series[currency]


class _StubOpenFigiClient:
    def __init__(self, identification: Identification) -> None:
        self._identification = identification

    async def resolve_by_isin(self, isin: str, currency: str, broker_market=None):
        return self._identification

    async def resolve_by_ticker(self, ticker: str, exch_code: str) -> Identification:
        return self._identification


def _client(
    tmp_path: Path,
    *,
    today: date,
    closes: _Closes | None = None,
    fx: _FakeFx | None = None,
    openfigi=None,
    quote_currency_fetcher=None,
) -> TestClient:
    app = create_app(
        db_path=tmp_path / "test.duckdb",
        openfigi_client_factory=lambda: openfigi,
        price_ratio_fetcher=lambda ticker, since: None,
        quote_currency_fetcher=quote_currency_fetcher or (lambda ticker: None),
        daily_closes_fetcher=closes or _Closes(),
        fx_client_factory=lambda: fx or _FakeFx(),
        today_provider=lambda: today,
    )
    return TestClient(app)


def _create_portfolio(client: TestClient, name: str = "XTB", broker: str = "xtb") -> str:
    response = client.post(
        "/api/portfolios", json={"name": name, "broker": broker, "account_type": "regular"}
    )
    return response.json()["id"]


def _import_xtb(client: TestClient, portfolio_id: str, workbook: bytes, valuation_date: str):
    response = client.post(
        f"/api/portfolios/{portfolio_id}/import",
        files={"file": ("positions.xlsx", workbook, XLSX_CONTENT_TYPE)},
        data={"valuation_date": valuation_date},
    )
    assert response.status_code == 201, response.text
    return response


def _series(body: dict) -> dict[str, str]:
    return dict(zip(body["dates"], body["totals"], strict=True))


def test_valuation_of_empty_portfolio_has_no_series(tmp_path: Path) -> None:
    with _client(tmp_path, today=date(2026, 1, 10)) as client:
        portfolio_id = _create_portfolio(client)

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

        assert body["dates"] == []
        assert body["total_value"] == "0"
        assert body["portfolios"][0]["current_value"] == "0"
        assert body["positions"] == []


def test_valuation_for_missing_portfolio_returns_404(tmp_path: Path) -> None:
    with _client(tmp_path, today=date(2026, 1, 10)) as client:
        response = client.get("/api/portfolios/00000000-0000-0000-0000-000000000000/valuation")

        assert response.status_code == 404


def test_xtb_lots_start_the_daily_history_before_the_import(tmp_path: Path) -> None:
    closes = _Closes(
        {
            "ISAC.L": {"2026-01-02": "100", "2026-01-05": "100", "2026-01-09": "110"},
            "ATR.WA": {"2026-01-02": "10", "2026-01-05": "10"},
        }
    )
    workbook = build_synthetic_xtb_workbook(
        lot_open_times=(datetime(2026, 1, 2, 10, 0), "03.01.2026 09:00:00")
    )
    with _client(tmp_path, today=date(2026, 1, 10), closes=closes) as client:
        portfolio_id = _create_portfolio(client)
        _import_xtb(client, portfolio_id, workbook, "2026-01-05")

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    series = _series(body)
    assert body["dates"][0] == "2026-01-02"  # the earliest lot, not the import
    assert body["dates"][-1] == "2026-01-10"
    assert series["2026-01-02"] == "2745.41"  # ISAC only, bought that day
    assert series["2026-01-03"] == "2798.71"  # + ATR's lot
    assert series["2026-01-05"] == "2798.71"  # the import's own stored values
    assert series["2026-01-09"] == "3073.25"  # ISAC's close +10%
    assert series["2026-01-10"] == "3073.25"  # no close that day: carries over
    assert body["total_value"] == "3073.25"
    assert body["prices_as_of"] == "2026-01-09"

    isac = next(p for p in body["positions"] if p["symbol"] == "ISAC.UK")
    assert isac["current_price"] == "503.3252"
    assert isac["price_currency"] == "PLN"
    assert isac["value"] == "3019.95"
    # avg_cost derived from XTB's own 59.4% return (#189): 1.594 * 1.1 - 1.
    assert isac["return_pct"] == "75.3"
    assert sum(D(p["value"]) for p in body["positions"]) == D(body["total_value"])

    assert [(c["date"], c["instrument_name"]) for c in body["changes"]] == [("2026-01-03", "Atrem")]


def test_imports_without_lots_hold_quantity_until_the_next_import(tmp_path: Path) -> None:
    closes = _Closes({"ISAC.L": {"2026-01-01": "100"}, "ATR.WA": {"2026-01-01": "10"}})
    with _client(tmp_path, today=date(2026, 1, 6), closes=closes) as client:
        portfolio_id = _create_portfolio(client)
        _import_xtb(client, portfolio_id, build_synthetic_xtb_workbook(), "2026-01-02")
        _import_xtb(client, portfolio_id, build_synthetic_xtb_workbook(), "2026-01-05")

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    assert body["dates"][0] == "2026-01-02"  # no lots: history starts at the first import
    assert set(_series(body).values()) == {"2798.71"}
    assert body["changes"] == []


def test_bossa_history_replays_the_ledger_day_by_day(tmp_path: Path) -> None:
    with _client(tmp_path, today=date(2026, 1, 6)) as client:
        portfolio_id = _create_portfolio(client, name="Bossa", broker="bossa")
        response = client.post(
            f"/api/portfolios/{portfolio_id}/import/bossa",
            files={"file": ("hisPW.csv", build_synthetic_bossa_csv(), "text/csv")},
            data={"valuation_date": "2026-01-06"},
        )
        assert response.status_code == 201, response.text

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    series = _series(body)
    # No resolved ticker, no market value: each instrument keeps its own
    # latest trade price (SYNTHA sold at 110, SYNTHB at 60).
    assert series["2026-01-01"] == "1400.00"  # 10 x 110 + 5 x 60
    assert series["2026-01-02"] == "1100.00"  # SYNTHB closed
    assert series["2026-01-05"] == "660.00"  # 4 SYNTHA sold
    assert series["2026-01-06"] == "660.00"
    changes = {(c["date"], c["instrument_name"], D(c["quantity_change"])) for c in body["changes"]}
    assert changes == {("2026-01-02", "SYNTHB", D(-5)), ("2026-01-05", "SYNTHA", D(-4))}
    assert any("SYNTHA" in w and "brak notowań" in w for w in body["warnings"])
    assert {p["isin"] for p in body["positions"]} == {SYNTH_A_ISIN}
    assert SYNTH_B_ISIN not in {p["instrument_key"] for p in body["positions"]}


def _import_bossa(client: TestClient, portfolio_id: str, csv_bytes: bytes, valuation_date: str):
    response = client.post(
        f"/api/portfolios/{portfolio_id}/import/bossa",
        files={"file": ("hisPW.csv", csv_bytes, "text/csv")},
        data={"valuation_date": valuation_date},
    )
    assert response.status_code == 201, response.text


def test_bossa_investment_counts_closed_and_open_positions(tmp_path: Path) -> None:
    with _client(tmp_path, today=date(2026, 1, 6)) as client:
        portfolio_id = _create_portfolio(client, name="Bossa", broker="bossa")
        _import_bossa(client, portfolio_id, build_synthetic_bossa_csv(), "2026-01-06")

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    investment = body["portfolios"][0]["investment"]
    assert investment["invested"] == "1256.00"  # 1005 + 251, after commission
    assert investment["proceeds"] == "737.00"  # 438 + 299
    assert investment["open_value"] == "660.00"  # 6 x 110
    assert investment["result"] == "141.00"  # SYNTHA +, SYNTHB closed at +48
    assert investment["not_covered"] == ["dividends"]


def _transaction_count(client: TestClient) -> int:
    return client.app.state.db.execute("SELECT count(*) FROM transactions").fetchone()[0]


def test_bossa_financial_history_alone_gives_the_complete_result(tmp_path: Path) -> None:
    with _client(tmp_path, today=date(2026, 1, 6)) as client:
        portfolio_id = _create_portfolio(client, name="Bossa", broker="bossa")
        response = client.post(
            f"/api/portfolios/{portfolio_id}/import/bossa",
            files={"file": ("hf.csv", build_synthetic_bossa_financial_csv(), "text/csv")},
            data={"valuation_date": "2026-01-06"},
        )
        assert response.status_code == 201, response.text
        assert response.json()["cash_operations_added"] == 3  # dividend, deposit, fee

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    investment = body["portfolios"][0]["investment"]
    assert investment["invested"] == "1256.00"  # the trades, exactly as from hisPW
    assert investment["proceeds"] == "737.00"
    assert investment["open_value"] == "660.00"
    assert investment["dividends"] == "12.50"
    assert investment["other"] == "-0.10"
    assert investment["net_deposits"] == "2000.00"
    assert investment["result"] == "153.40"  # 141.00 + 12.50 - 0.10
    assert investment["not_covered"] == []
    assert {p["isin"] for p in body["positions"]} == {SYNTH_A_ISIN}


def test_return_index_leaves_out_sales_and_counts_the_dividend(tmp_path: Path) -> None:
    # #273: no quotes, so every instrument keeps its trade price -- the
    # value falls with each sale, but nothing moved in price; only the
    # 12.50 dividend on 3 Jan (set against 1100 held) is a return.
    with _client(tmp_path, today=date(2026, 1, 6)) as client:
        portfolio_id = _create_portfolio(client, name="Bossa", broker="bossa")
        _import_bossa(client, portfolio_id, build_synthetic_bossa_financial_csv(), "2026-01-06")

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    portfolio = body["portfolios"][0]
    assert portfolio["values"] == ["1400.00", "1100.00", "1100.00", "1100.00", "660.00", "660.00"]
    assert portfolio["prior_holdings_values"] == [
        "0.00",
        "1400.00",
        "1100.00",
        "1100.00",
        "1100.00",
        "660.00",
    ]
    assert portfolio["dividends_by_day"] == {"2026-01-03": "12.50"}
    assert portfolio["dividends_included"] is True
    # Nothing has daily quotes here: all of it is held at a constant value,
    # and the only gain the history sees is the dividend -- against a result
    # of 153.40 from the cash flows.
    assert portfolio["unquoted_values"] == portfolio["values"]
    assert portfolio["history_gain"] == "12.50"
    assert portfolio["investment"]["result"] == "153.40"
    assert portfolio["deposits_by_day"] == {"2026-01-01": "2000.00"}
    assert portfolio["deposits_before_start"] == "0.00"
    assert body["return_index"] == [
        "1.000000",
        "1.000000",
        "1.011364",
        "1.011364",
        "1.011364",
        "1.011364",
    ]


def test_ledger_without_financial_history_flags_return_without_dividends(
    tmp_path: Path,
) -> None:
    with _client(tmp_path, today=date(2026, 1, 6)) as client:
        portfolio_id = _create_portfolio(client, name="Bossa", broker="bossa")
        _import_bossa(client, portfolio_id, build_synthetic_bossa_csv(), "2026-01-06")

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    assert body["portfolios"][0]["dividends_by_day"] == {}
    assert body["portfolios"][0]["dividends_included"] is False
    assert set(body["return_index"]) == {"1.000000"}


def test_bossa_trades_are_not_doubled_whichever_file_comes_first(tmp_path: Path) -> None:
    def upload(client, portfolio_id, name, content):
        response = client.post(
            f"/api/portfolios/{portfolio_id}/import/bossa",
            files={"file": (name, content, "text/csv")},
            data={"valuation_date": "2026-01-06"},
        )
        assert response.status_code == 201, response.text

    with _client(tmp_path, today=date(2026, 1, 6)) as client:
        his_first = _create_portfolio(client, name="A", broker="bossa")
        upload(client, his_first, "hisPW.csv", build_synthetic_bossa_csv())
        upload(client, his_first, "hf.csv", build_synthetic_bossa_financial_csv())
        after_his_first = _transaction_count(client)

        financial_first = _create_portfolio(client, name="B", broker="bossa")
        upload(client, financial_first, "hf.csv", build_synthetic_bossa_financial_csv())
        upload(client, financial_first, "hisPW.csv", build_synthetic_bossa_csv())
        upload(client, financial_first, "hf.csv", build_synthetic_bossa_financial_csv())
        total = _transaction_count(client)

        bodies = [
            client.get(f"/api/portfolios/{i}/valuation").json()
            for i in (his_first, financial_first)
        ]

    assert after_his_first == 4
    assert total - after_his_first == 4  # portfolio B: four trades, however imported
    for body in bodies:
        assert body["portfolios"][0]["investment"]["invested"] == "1256.00"
        assert body["portfolios"][0]["investment"]["open_value"] == "660.00"


def test_the_same_financial_history_in_two_portfolios_is_two_sets_of_trades(
    tmp_path: Path,
) -> None:
    with _client(tmp_path, today=date(2026, 1, 6)) as client:
        for name in ("Konto 1", "Konto 2"):
            portfolio_id = _create_portfolio(client, name=name, broker="bossa")
            _import_bossa(client, portfolio_id, build_synthetic_bossa_financial_csv(), "2026-01-06")

        assert _transaction_count(client) == 8


def test_reimporting_the_financial_history_adds_nothing(tmp_path: Path) -> None:
    with _client(tmp_path, today=date(2026, 1, 6)) as client:
        portfolio_id = _create_portfolio(client, name="Bossa", broker="bossa")
        added = []
        for _ in range(2):
            response = client.post(
                f"/api/portfolios/{portfolio_id}/import/bossa",
                files={"file": ("hf.csv", build_synthetic_bossa_financial_csv(), "text/csv")},
                data={"valuation_date": "2026-01-06"},
            )
            added.append(response.json()["cash_operations_added"])

        count = _transaction_count(client)
        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    assert added == [3, 0]
    assert count == 4
    assert body["portfolios"][0]["investment"]["dividends"] == "12.50"


def test_identical_fills_on_one_day_are_both_kept(tmp_path: Path) -> None:
    fill = bossa_settlement_row(
        "2026-01-04", "kupna", "SYNTHA", SYNTH_A_ISIN, "1", "100.00", "PLN", "-100,00"
    )
    content = build_synthetic_bossa_financial_csv([fill, fill], with_cash_rows=False)
    with _client(tmp_path, today=date(2026, 1, 6)) as client:
        portfolio_id = _create_portfolio(client, name="Bossa", broker="bossa")
        for _ in range(2):  # the second upload must not add a third or fourth
            client.post(
                f"/api/portfolios/{portfolio_id}/import/bossa",
                files={"file": ("hf.csv", content, "text/csv")},
                data={"valuation_date": "2026-01-06"},
            )

        assert _transaction_count(client) == 6  # the four base trades + two fills


def test_bossa_dividend_in_dollars_is_converted_on_its_own_day(tmp_path: Path) -> None:
    fx = _FakeFx({"USD": {"2026-01-03": "4.00", "2026-01-06": "4.20"}})
    rows = ["2026-01-03;Wypłata dywidendy netto ABC 85% USD;;10,00;USD"]
    content = build_synthetic_bossa_financial_csv(rows, with_cash_rows=False)
    with _client(tmp_path, today=date(2026, 1, 6), fx=fx) as client:
        portfolio_id = _create_portfolio(client, name="Bossa", broker="bossa")
        _import_bossa(client, portfolio_id, content, "2026-01-06")

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    assert body["portfolios"][0]["investment"]["dividends"] == "40.00"


def test_import_reports_financial_history_titles_it_does_not_know(tmp_path: Path) -> None:
    content = build_synthetic_bossa_financial_csv(
        ["2026-01-04;Coś zupełnie nowego;;5,00;PLN"], with_cash_rows=False
    )
    with _client(tmp_path, today=date(2026, 1, 6)) as client:
        portfolio_id = _create_portfolio(client, name="Bossa", broker="bossa")

        response = client.post(
            f"/api/portfolios/{portfolio_id}/import/bossa",
            files={"file": ("hf.csv", content, "text/csv")},
            data={"valuation_date": "2026-01-06"},
        )

    assert any("Coś zupełnie nowego" in w for w in response.json()["warnings"])


def test_investment_converts_each_trade_at_its_own_day_rate(tmp_path: Path) -> None:
    csv_rows = [
        "data;papier;isin;ilość;-;cena;wartość;prowizja;po prowizji;waluta",
        f"01.01.2026 10:00:00;SYNTHA;{SYNTH_A_ISIN};10;K;100,00;1000,00;0,00;1000,00;USD",
    ]
    csv_bytes = ("\r\n".join(csv_rows) + "\r\n").encode("cp1250")
    fx = _FakeFx({"USD": {"2026-01-01": "4.00", "2026-01-06": "4.20"}})
    with _client(tmp_path, today=date(2026, 1, 6), fx=fx) as client:
        portfolio_id = _create_portfolio(client, name="Bossa", broker="bossa")
        _import_bossa(client, portfolio_id, csv_bytes, "2026-01-06")

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    investment = body["portfolios"][0]["investment"]
    assert investment["invested"] == "4000.00"  # 1000 USD at 4.00
    assert investment["open_value"] == "4200.00"  # 1000 USD at today's 4.20
    assert investment["result"] == "200.00"  # the currency move counts


def test_investment_is_absent_when_a_needed_rate_is_missing(tmp_path: Path) -> None:
    csv_rows = [
        "data;papier;isin;ilość;-;cena;wartość;prowizja;po prowizji;waluta",
        f"01.01.2026 10:00:00;SYNTHA;{SYNTH_A_ISIN};10;K;100,00;1000,00;0,00;1000,00;USD",
    ]
    csv_bytes = ("\r\n".join(csv_rows) + "\r\n").encode("cp1250")
    with _client(tmp_path, today=date(2026, 1, 6)) as client:  # no USD series
        portfolio_id = _create_portfolio(client, name="Bossa", broker="bossa")
        _import_bossa(client, portfolio_id, csv_bytes, "2026-01-06")

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    assert body["portfolios"][0]["investment"] is None
    assert any("wynik inwestycji pominięty" in w for w in body["warnings"])


def test_xtb_investment_compares_current_value_with_cost_of_open_positions(
    tmp_path: Path,
) -> None:
    closes = _Closes({"ISAC.L": {"2026-01-01": "100"}, "ATR.WA": {"2026-01-01": "10"}})
    with _client(tmp_path, today=date(2026, 1, 6), closes=closes) as client:
        portfolio_id = _create_portfolio(client)
        _import_xtb(client, portfolio_id, build_synthetic_xtb_workbook(), "2026-01-05")

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    investment = body["portfolios"][0]["investment"]
    cost = sum(D(p["avg_cost"]) * D(p["quantity"]) for p in body["positions"])
    assert abs(D(investment["invested"]) - cost) <= D("0.01")
    assert investment["proceeds"] == "0.00"
    assert investment["open_value"] == body["total_value"]
    assert investment["not_covered"] == ["closed_positions", "dividends"]


CASH_DAY = datetime(2026, 1, 2, 10, 0, 0)
LATER_DAY = datetime(2026, 1, 6, 10, 0, 0)


def _import_xtb_with_cash(
    client: TestClient, portfolio_id: str, operations, *, account_currency: str = "PLN"
):
    workbook = build_synthetic_xtb_workbook(
        cash_operations=operations, account_currency=account_currency
    )
    return _import_xtb(client, portfolio_id, workbook, "2026-01-05")


def test_xtb_cash_operations_make_the_investment_result_complete(tmp_path: Path) -> None:
    closes = _Closes({"ISAC.L": {"2026-01-01": "100"}, "ATR.WA": {"2026-01-01": "10"}})
    operations = [
        ("Deposit", "", CASH_DAY, 9999.0, "1"),  # never part of the result
        ("Stock purchase", "MSCI ACWI", CASH_DAY, -1000.0, "2"),
        ("Stock purchase", "Atrem", CASH_DAY, -500.0, "3"),
        ("Stock sell", "Old", CASH_DAY, 300.0, "4"),  # a position closed since
        ("Dividend", "Atrem", CASH_DAY, 10.0, "5"),
        ("Withholding tax", "Atrem", CASH_DAY, -1.5, "6"),
        ("Free funds interest", "", CASH_DAY, 0.08, "7"),
        ("Free funds interest tax", "", CASH_DAY, -0.02, "8"),
        ("SEC fee", "Old", CASH_DAY, -0.5, "9"),
    ]
    with _client(tmp_path, today=date(2026, 1, 6), closes=closes) as client:
        portfolio_id = _create_portfolio(client)
        _import_xtb_with_cash(client, portfolio_id, operations)

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    investment = body["portfolios"][0]["investment"]
    assert investment["invested"] == "1500.00"
    assert investment["proceeds"] == "300.00"
    assert investment["dividends"] == "8.50"  # after withholding tax
    assert investment["interest"] == "0.06"
    assert investment["other"] == "-0.50"
    assert investment["net_deposits"] == "9999.00"  # the base of the percentage, not of the result
    assert investment["open_value"] == body["total_value"]
    expected = D("300") + D(body["total_value"]) - D("1500") + D("8.50") + D("0.06") - D("0.50")
    assert D(investment["result"]) == expected
    assert investment["not_covered"] == []


def test_foreign_currency_dividend_is_converted_on_its_own_day(tmp_path: Path) -> None:
    fx = _FakeFx({"USD": {"2026-01-02": "4.00", "2026-01-06": "4.20"}})
    operations = [
        ("Stock purchase", "MSCI ACWI", CASH_DAY, -100.0, "1"),
        ("Dividend", "MSCI ACWI", CASH_DAY, 10.0, "2"),
        ("Dividend", "MSCI ACWI", LATER_DAY, 10.0, "3"),
    ]
    with _client(tmp_path, today=date(2026, 1, 6), fx=fx) as client:
        portfolio_id = _create_portfolio(client)
        _import_xtb_with_cash(client, portfolio_id, operations, account_currency="USD")

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    investment = body["portfolios"][0]["investment"]
    assert investment["invested"] == "400.00"  # 100 USD at 4.00
    assert investment["dividends"] == "82.00"  # 10 x 4.00 + 10 x 4.20


def test_net_deposits_convert_each_transfer_on_its_own_day(tmp_path: Path) -> None:
    fx = _FakeFx({"USD": {"2026-01-02": "4.00", "2026-01-06": "4.20"}})
    operations = [
        ("Deposit", "", CASH_DAY, 1000.0, "1"),
        ("Withdrawal", "", LATER_DAY, -200.0, "2"),
        ("Stock purchase", "MSCI ACWI", CASH_DAY, -100.0, "3"),  # a result needs a purchase
    ]
    with _client(tmp_path, today=date(2026, 1, 6), fx=fx) as client:
        portfolio_id = _create_portfolio(client)
        _import_xtb_with_cash(client, portfolio_id, operations, account_currency="USD")

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    portfolio = body["portfolios"][0]
    assert portfolio["investment"]["net_deposits"] == "3160.00"  # 4000 - 840
    # #273: the same deposits, day by day (and before the chart's first
    # day), add up to the net deposits of the investment result.
    by_day = sum((D(amount) for amount in portfolio["deposits_by_day"].values()), D(0))
    assert by_day + D(portfolio["deposits_before_start"]) == D("3160.00")


def test_net_deposits_are_absent_when_the_file_has_no_transfers(tmp_path: Path) -> None:
    operations = [("Stock purchase", "Atrem", CASH_DAY, -500.0, "1")]
    with _client(tmp_path, today=date(2026, 1, 6)) as client:
        portfolio_id = _create_portfolio(client)
        _import_xtb_with_cash(client, portfolio_id, operations)

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    assert body["portfolios"][0]["investment"]["net_deposits"] is None


OLD_OPENED = datetime(2026, 1, 1, 10, 0, 0)
OLD_CLOSED = datetime(2026, 1, 4, 16, 0, 0)


def _sold_lot(ticker: str = "OLD.PL", name: str = "Old co"):
    """10 units bought 2026-01-01 for 400 and sold 2026-01-04 for 450 (PLN)."""
    return (name, ticker, "BUY", 10.0, 40.0, OLD_OPENED, OLD_CLOSED, 400.0, 450.0)


def _import_xtb_with_lots(client: TestClient, portfolio_id: str, lots, *, lot_times=True):
    workbook = build_synthetic_xtb_workbook(
        closed_positions=lots,
        lot_open_times=(datetime(2026, 1, 2, 10, 0), "03.01.2026 09:00:00") if lot_times else None,
    )
    return _import_xtb(client, portfolio_id, workbook, "2026-01-05")


def test_a_sold_instrument_is_part_of_the_history_while_it_was_held(tmp_path: Path) -> None:
    closes = _Closes(
        {
            "ISAC.L": {"2026-01-02": "100", "2026-01-05": "100", "2026-01-09": "110"},
            "ATR.WA": {"2026-01-02": "10", "2026-01-05": "10"},
            "OLD.WA": {"2026-01-01": "10", "2026-01-04": "11"},
        }
    )
    with _client(tmp_path, today=date(2026, 1, 10), closes=closes) as client:
        portfolio_id = _create_portfolio(client)
        response = _import_xtb_with_lots(client, portfolio_id, [_sold_lot()])
        assert response.json()["closed_lots_added"] == 1

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    series = _series(body)
    assert body["dates"][0] == "2026-01-01"  # the sold lot's purchase, before any open lot
    # 10 units at the last sale price (45) moved back by OLD's own closes (10 vs 11)
    assert series["2026-01-01"] == "409.09"
    assert series["2026-01-02"] == "3154.50"  # + ISAC's lot (2745.41)
    assert series["2026-01-03"] == "3207.80"  # + ATR's lot (53.30)
    assert series["2026-01-04"] == "2798.71"  # OLD sold that day
    assert series["2026-01-10"] == "3073.25"  # as before: only what is still held
    assert body["total_value"] == "3073.25"
    sold = [c for c in body["changes"] if c["instrument_name"] == "Old co"]
    # the purchase is the series' starting state; only the sale is a change
    assert [(c["date"], c["quantity_change"]) for c in sold] == [("2026-01-04", "-10.00000000")]


def test_an_open_position_without_dated_lots_counts_from_the_import_day(tmp_path: Path) -> None:
    closes = _Closes({"OLD.WA": {"2026-01-01": "10", "2026-01-04": "11"}})
    with _client(tmp_path, today=date(2026, 1, 6), closes=closes) as client:
        portfolio_id = _create_portfolio(client)
        _import_xtb_with_lots(client, portfolio_id, [_sold_lot()], lot_times=False)

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    series = _series(body)
    assert series["2026-01-04"] == "0.00"  # OLD sold, nothing else held yet
    assert series["2026-01-05"] == "2798.71"  # the import day
    assert body["total_value"] == "2798.71"


def test_an_instrument_without_a_quotable_symbol_is_left_out_with_a_note(tmp_path: Path) -> None:
    lots = [_sold_lot(), _sold_lot("SOLANA", "Solana")]
    with _client(tmp_path, today=date(2026, 1, 10)) as client:
        portfolio_id = _create_portfolio(client)
        _import_xtb_with_lots(client, portfolio_id, lots)

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    assert all(c["instrument_name"] != "Solana" for c in body["changes"])
    assert any("Solana" in w and "pominiętych w historii" in w for w in body["warnings"])


def test_reimporting_closed_positions_adds_nothing_and_short_lots_are_reported(
    tmp_path: Path,
) -> None:
    short = ("Short", "SHORT.US", "SELL", 1.0, 5.0, OLD_OPENED, OLD_CLOSED, 5.0, 4.0)
    with _client(tmp_path, today=date(2026, 1, 10)) as client:
        portfolio_id = _create_portfolio(client)
        first = _import_xtb_with_lots(client, portfolio_id, [_sold_lot(), short]).json()
        again = _import_xtb_with_lots(client, portfolio_id, [_sold_lot(), short]).json()

    assert (first["closed_lots_added"], again["closed_lots_added"]) == (1, 0)
    assert any("pozycji krótkich" in w for w in first["warnings"])


def test_import_without_closed_positions_reports_none(tmp_path: Path) -> None:
    with _client(tmp_path, today=date(2026, 1, 6)) as client:
        portfolio_id = _create_portfolio(client)
        body = _import_xtb(
            client, portfolio_id, build_synthetic_xtb_workbook(), "2026-01-05"
        ).json()

    assert body["closed_lots_added"] is None


def test_reimporting_an_overlapping_export_adds_only_new_operations(tmp_path: Path) -> None:
    first = [
        ("Stock purchase", "Atrem", CASH_DAY, -500.0, "1"),
        ("Dividend", "Atrem", CASH_DAY, 10.0, "2"),
    ]
    later = [*first, ("Dividend", "Atrem", LATER_DAY, 5.0, "3")]
    with _client(tmp_path, today=date(2026, 1, 6)) as client:
        portfolio_id = _create_portfolio(client)

        added_first = _import_xtb_with_cash(client, portfolio_id, first).json()
        added_later = _import_xtb_with_cash(client, portfolio_id, later).json()
        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    assert added_first["cash_operations_added"] == 2
    assert added_later["cash_operations_added"] == 1
    assert body["portfolios"][0]["investment"]["dividends"] == "15.00"


def test_import_reports_operation_types_it_does_not_know(tmp_path: Path) -> None:
    operations = [("Crypto staking reward", "X", CASH_DAY, 3.0, "1")]
    with _client(tmp_path, today=date(2026, 1, 6)) as client:
        portfolio_id = _create_portfolio(client)

        body = _import_xtb_with_cash(client, portfolio_id, operations).json()

    assert any("Crypto staking reward" in warning for warning in body["warnings"])
    assert body["cash_operations_added"] == 0


def test_import_without_cash_operations_reports_none(tmp_path: Path) -> None:
    with _client(tmp_path, today=date(2026, 1, 6)) as client:
        portfolio_id = _create_portfolio(client)

        workbook = build_synthetic_xtb_workbook()
        body = _import_xtb(client, portfolio_id, workbook, "2026-01-05").json()

    assert body["cash_operations_added"] is None
    assert body["warnings"] == []


def test_manual_position_investment_is_value_minus_stated_cost(tmp_path: Path) -> None:
    today = date.today()
    with _client(tmp_path, today=today) as client:
        portfolio_id = _create_portfolio(client)
        client.post(
            f"/api/portfolios/{portfolio_id}/positions",
            json={
                "instrument_name": "Obligacje",
                "symbol": "MAN.PL",
                "asset_class": "bond",
                "quantity": "10",
                "avg_cost": "100",
            },
        )

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    investment = body["portfolios"][0]["investment"]
    assert investment["invested"] == "1000.00"
    assert investment["result"] == "0.00"


def test_all_portfolios_valuation_sums_every_portfolio_on_one_axis(tmp_path: Path) -> None:
    closes = _Closes({"ISAC.L": {"2026-01-01": "100"}, "ATR.WA": {"2026-01-01": "10"}})
    with _client(tmp_path, today=date(2026, 1, 6), closes=closes) as client:
        xtb_id = _create_portfolio(client)
        _import_xtb(client, xtb_id, build_synthetic_xtb_workbook(), "2026-01-04")
        bossa_id = _create_portfolio(client, name="Bossa", broker="bossa")
        client.post(
            f"/api/portfolios/{bossa_id}/import/bossa",
            files={"file": ("hisPW.csv", build_synthetic_bossa_csv(), "text/csv")},
            data={"valuation_date": "2026-01-06"},
        )
        _create_portfolio(client, name="Pusty")

        body = client.get("/api/valuation").json()

    assert body["dates"][0] == "2026-01-01"  # Bossa's first trade
    by_name = {p["name"]: p for p in body["portfolios"]}
    assert set(by_name) == {"XTB", "Bossa", "Pusty"}
    xtb_values = dict(zip(body["dates"], by_name["XTB"]["values"], strict=True))
    assert xtb_values["2026-01-03"] == "0.00"  # before its import
    assert xtb_values["2026-01-04"] == "2798.71"
    assert _series(body)["2026-01-06"] == "3458.71"  # 2798.71 + 660
    assert body["total_value"] == "3458.71"
    assert by_name["Pusty"]["current_value"] == "0.00"
    assert {p["portfolio_id"] for p in body["positions"]} == {xtb_id, bossa_id}


def test_manual_position_is_valued_at_its_own_figure(tmp_path: Path) -> None:
    today = date.today()  # a manual position is dated the day it's entered
    closes = _Closes({"MAN.PL": {today.isoformat(): "999"}})
    with _client(tmp_path, today=today, closes=closes) as client:
        portfolio_id = _create_portfolio(client)
        created = client.post(
            f"/api/portfolios/{portfolio_id}/positions",
            json={
                "instrument_name": "Obligacje",
                "symbol": "MAN.PL",
                "asset_class": "bond",
                "quantity": "10",
                "avg_cost": "100",
            },
        )
        assert created.status_code == 201

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    assert body["total_value"] == "1000.00"
    (position,) = body["positions"]
    assert position["is_manual"] is True
    assert position["current_price"] == "100.0000"
    assert position["return_pct"] == "0.0"
    assert closes.calls == []  # never re-priced from market data


def test_manual_position_steps_at_each_valuation_from_its_purchase_date(tmp_path: Path) -> None:
    # #288: a gold coin bought on Jan 2, valued by the owner on Jan 5 and Jan 8.
    with _client(tmp_path, today=date(2026, 1, 10)) as client:
        portfolio_id = _create_portfolio(client)
        coin = client.post(
            f"/api/portfolios/{portfolio_id}/positions",
            json={
                "instrument_name": "Krugerrand 1 oz",
                "asset_class": "other",
                "quantity": "2",
                "avg_cost": "100",
                "purchased_on": "2026-01-02",
            },
        ).json()
        url = f"/api/portfolios/{portfolio_id}/positions/{coin['id']}/valuations"
        client.put(f"{url}/2026-01-05", json={"unit_value": "120"})
        client.put(f"{url}/2026-01-08", json={"unit_value": "90"})

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    assert body["dates"][0] == "2026-01-02"  # history starts on the purchase date
    values = _series(body)
    assert [values[f"2026-01-0{day}"] for day in (2, 4, 5, 7, 8)] == [
        "200.00",
        "200.00",
        "240.00",
        "240.00",
        "180.00",
    ]
    assert values["2026-01-10"] == "180.00"
    (position,) = body["positions"]
    assert position["current_price"] == "90.0000"
    assert position["return_pct"] == "-10.0"
    assert position["valued_on"] == "2026-01-08"
    assert position["price_date"] is None  # no daily quotes, still
    investment = body["portfolios"][0]["investment"]
    assert investment["invested"] == "200.00"
    assert investment["result"] == "-20.00"


def test_failed_quote_lookup_degrades_to_constant_value_with_warning(tmp_path: Path) -> None:
    def failing(ticker: str, start: date, refresh: bool):
        raise ConnectionError("blocked")

    with _client(tmp_path, today=date(2026, 1, 6), closes=failing) as client:
        portfolio_id = _create_portfolio(client)
        _import_xtb(client, portfolio_id, build_synthetic_xtb_workbook(), "2026-01-05")

        response = client.get(f"/api/portfolios/{portfolio_id}/valuation")

    assert response.status_code == 200
    body = response.json()
    assert body["total_value"] == "2798.71"
    assert body["prices_as_of"] is None
    assert len([w for w in body["warnings"] if "brak notowań" in w]) == 2


def test_refresh_is_passed_to_the_quote_fetcher(tmp_path: Path) -> None:
    closes = _Closes()
    with _client(tmp_path, today=date(2026, 1, 6), closes=closes) as client:
        portfolio_id = _create_portfolio(client)
        _import_xtb(client, portfolio_id, build_synthetic_xtb_workbook(), "2026-01-05")

        client.get(f"/api/portfolios/{portfolio_id}/valuation")
        client.get(f"/api/portfolios/{portfolio_id}/valuation?refresh=true")

    assert {refresh for _, _, refresh in closes.calls} == {False, True}


def test_unresolved_xtb_position_is_priced_under_its_yahoo_symbol(tmp_path: Path) -> None:
    # No OpenFIGI client, so nothing resolves: XTB's own symbol, in Yahoo's
    # form (ATR.PL -> ATR.WA), still prices the position (#250).
    closes = _Closes({"ATR.WA": {"2026-01-05": "10", "2026-01-06": "11"}})
    with _client(tmp_path, today=date(2026, 1, 6), closes=closes) as client:
        portfolio_id = _create_portfolio(client)
        _import_xtb(client, portfolio_id, build_synthetic_xtb_workbook(), "2026-01-05")

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    assert {ticker for ticker, _, _ in closes.calls} == {"ISAC.L", "ATR.WA"}
    # ISAC.L has no closes and stays at 2745.41; Atrem's 53.30 moves +10%.
    assert _series(body)["2026-01-06"] == "2804.04"


def test_xtb_suffix_names_the_quote_currency_of_an_unresolved_position(tmp_path: Path) -> None:
    # The issue's case (#250): a US stock OpenFIGI didn't find, here in a
    # PLN account. ".US" says it trades in USD, so USD/PLN moves its value.
    closes = _Closes({"GOOGL": {"2026-01-05": "100", "2026-01-06": "100"}})
    fx = _FakeFx({"USD": {"2026-01-05": "4.00", "2026-01-06": "4.20"}})
    with _client(tmp_path, today=date(2026, 1, 6), closes=closes, fx=fx) as client:
        portfolio_id = _create_portfolio(client)
        _import_xtb(client, portfolio_id, build_synthetic_xtb_workbook(), "2026-01-05")
        client.app.state.db.execute(
            "UPDATE positions SET symbol = 'GOOGL.US' WHERE symbol = 'ISAC.UK'"
        )

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    assert fx.requested == ["USD"]
    # Same USD price, USD/PLN +5%: 2745.41 * 1.05 + Atrem's 53.30.
    assert _series(body)["2026-01-06"] == "2935.98"


def test_foreign_quote_currency_value_moves_with_nbp_rate(tmp_path: Path) -> None:
    # Every position resolves to ISAC on LSE, quoted in USD in a PLN account.
    stub = _StubOpenFigiClient(
        Identification(status="resolved", figi="BBG00265DDD0", ticker="ISAC", exchange_code="LN")
    )
    closes = _Closes({"ISAC.L": {"2026-01-05": "100", "2026-01-06": "100"}})
    fx = _FakeFx({"USD": {"2026-01-05": "4.00", "2026-01-06": "4.20"}})
    with _client(
        tmp_path,
        today=date(2026, 1, 6),
        closes=closes,
        fx=fx,
        openfigi=stub,
        quote_currency_fetcher=lambda ticker: "USD",
    ) as client:
        portfolio_id = _create_portfolio(client)
        _import_xtb(client, portfolio_id, build_synthetic_xtb_workbook(), "2026-01-05")

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    assert fx.requested == ["USD"]
    series = _series(body)
    assert series["2026-01-05"] == "2798.71"
    # Same USD price, USD/PLN +5%: 2798.71 * 1.05.
    assert series["2026-01-06"] == "2938.65"


class _ListingsOpenFigi:
    """Leaves every held position as the import's lookup leaves a US stock in
    a Bossa account (`identification`, ambiguous by default) and lists canned
    listings per ISIN for the ledger's own lookup (#277)."""

    def __init__(
        self,
        listings: dict[str, list[Listing]],
        identification: Identification | None = None,
    ) -> None:
        self._listings = listings
        self._identification = identification or Identification(status="ambiguous")
        self.listing_jobs: list[tuple[str, str | None]] = []

    async def resolve_by_isin(self, isin: str, currency: str, broker_market=None):
        return self._identification

    async def resolve_by_ticker(self, ticker: str, exch_code: str) -> Identification:
        return self._identification

    async def listings_by_isin(self, jobs: list[tuple[str, str | None]]) -> list[list[Listing]]:
        self.listing_jobs.extend(jobs)
        return [self._listings.get(isin, []) for isin, _ in jobs]


def test_sold_and_held_bossa_instruments_move_with_their_listing(tmp_path: Path) -> None:
    # #277: SYNTHB is sold, SYNTHA held but ambiguous at import -- neither
    # has a ticker of its own, both get one from the ledger's lookup.
    openfigi = _ListingsOpenFigi(
        {
            SYNTH_A_ISIN: [Listing(ticker="SYA", exchange_code="PW")],
            SYNTH_B_ISIN: [Listing(ticker="SYB", exchange_code="PW")],
        }
    )
    closes = _Closes(
        {
            "SYA.WA": {"2026-01-01": "100", "2026-01-05": "110", "2026-01-06": "121"},
            "SYB.WA": {"2026-01-01": "55", "2026-01-02": "60"},
        }
    )
    with _client(
        tmp_path,
        today=date(2026, 1, 6),
        closes=closes,
        openfigi=openfigi,
        quote_currency_fetcher=lambda ticker: "PLN",
    ) as client:
        portfolio_id = _create_portfolio(client, name="Bossa", broker="bossa")
        _import_bossa(client, portfolio_id, build_synthetic_bossa_csv(), "2026-01-06")
        _import_bossa(client, portfolio_id, build_synthetic_bossa_csv(), "2026-01-06")

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    # Asked once per ISIN: the second import finds both already identified.
    assert sorted(openfigi.listing_jobs) == [(SYNTH_A_ISIN, "PLN"), (SYNTH_B_ISIN, "PLN")]
    series = _series(body)
    assert series["2026-01-01"] == "1275.00"  # 10 x 100 + 5 x 55
    assert series["2026-01-02"] == "1000.00"  # SYNTHB sold
    assert series["2026-01-05"] == "660.00"  # 6 x 110, the trade price
    assert series["2026-01-06"] == "726.00"  # 6 x 121
    assert not [w for w in body["warnings"] if "brak notowań" in w]
    assert body["portfolios"][0]["unquoted_values"][-1] == "0.00"


def test_pln_trade_of_a_foreign_listing_moves_with_its_quote_currency(tmp_path: Path) -> None:
    # Moderna's case (#277): bought in PLN, priced by its USD listing -- the
    # listing's quote currency brings USD/PLN into the value.
    openfigi = _ListingsOpenFigi({SYNTH_A_ISIN: [Listing(ticker="SYA", exchange_code="US")]})
    closes = _Closes({"SYA": {"2026-01-01": "10", "2026-01-06": "10"}})
    fx = _FakeFx({"USD": {"2026-01-01": "4.00", "2026-01-05": "4.00", "2026-01-06": "4.40"}})
    with _client(
        tmp_path,
        today=date(2026, 1, 6),
        closes=closes,
        fx=fx,
        openfigi=openfigi,
        quote_currency_fetcher=lambda ticker: "USD",
    ) as client:
        portfolio_id = _create_portfolio(client, name="Bossa", broker="bossa")
        _import_bossa(client, portfolio_id, build_synthetic_bossa_csv(), "2026-01-06")

        body = client.get(f"/api/portfolios/{portfolio_id}/valuation").json()

    # 110 PLN on 5 Jan, flat in USD, USD/PLN +10% on 6 Jan.
    assert _series(body)["2026-01-06"] == "726.00"


def test_a_position_s_own_ticker_wins_over_the_ledger_listing(tmp_path: Path) -> None:
    openfigi = _ListingsOpenFigi(
        {SYNTH_A_ISIN: [Listing(ticker="OTHER", exchange_code="PW")]},
        Identification(status="resolved", ticker="OWN", exchange_code="PW"),
    )
    closes = _Closes()
    with _client(tmp_path, today=date(2026, 1, 6), closes=closes, openfigi=openfigi) as client:
        portfolio_id = _create_portfolio(client, name="Bossa", broker="bossa")
        _import_bossa(client, portfolio_id, build_synthetic_bossa_csv(), "2026-01-06")

        client.get(f"/api/portfolios/{portfolio_id}/valuation")

    assert {ticker for ticker, _, _ in closes.calls} == {"OWN.WA"}
