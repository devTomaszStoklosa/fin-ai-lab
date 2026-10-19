from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from portfolio_xray._fixtures import build_synthetic_xtb_workbook  # noqa: E402

from fin_ai_lab.portfolio_webapp.api import create_app  # noqa: E402

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# The synthetic XTB export holds ISAC.UK (2745.41 PLN) and 1 x ATR.PL "Atrem"
# (53.30 PLN); the Bossa ledger below buys the same company as "ATREM".
ISAC, XTB_ATR = "xtb:ISAC.UK", "xtb:ATR.PL"
ATR_ISIN = "PLATREM00017"


class _NoFx:
    async def mid_rate_series(self, currency: str, start: date, end: date) -> dict:
        raise LookupError(currency)


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(
        db_path=tmp_path / "test.duckdb",
        openfigi_client_factory=lambda: None,
        price_ratio_fetcher=lambda ticker, since: None,
        quote_currency_fetcher=lambda ticker: None,
        daily_closes_fetcher=lambda ticker, start, refresh: None,
        fx_client_factory=_NoFx,
        today_provider=lambda: date(2026, 1, 10),
    )
    with TestClient(app) as test_client:
        yield test_client


def _portfolio(client: TestClient, name: str, broker: str) -> str:
    return client.post(
        "/api/portfolios", json={"name": name, "broker": broker, "account_type": "regular"}
    ).json()["id"]


def _xtb_and_bossa(client: TestClient) -> tuple[str, str]:
    xtb_id = _portfolio(client, "XTB", "xtb")
    response = client.post(
        f"/api/portfolios/{xtb_id}/import",
        files={"file": ("p.xlsx", build_synthetic_xtb_workbook(), XLSX_CONTENT_TYPE)},
        data={"valuation_date": "2026-01-05"},
    )
    assert response.status_code == 201, response.text

    bossa_id = _portfolio(client, "Bossa", "bossa")
    ledger = (
        "data;papier;isin;ilość;-;cena;wartość;prowizja;po prowizji;waluta\r\n"
        f"02.01.2026 10:00:00;ATREM;{ATR_ISIN};2;K;53,00;106,00;1,00;107,00;PLN\r\n"
    ).encode("cp1250")
    response = client.post(
        f"/api/portfolios/{bossa_id}/import/bossa",
        files={"file": ("hisPW.csv", ledger, "text/csv")},
        data={"valuation_date": "2026-01-05"},
    )
    assert response.status_code == 201, response.text
    return xtb_id, bossa_id


def _link(client: TestClient, key_a: str, key_b: str, *, same: bool = True):
    return client.post(
        "/api/instruments/links", json={"key_a": key_a, "key_b": key_b, "same": same}
    )


def _assets(client: TestClient) -> dict[str, dict]:
    return {a["instrument_key"]: a for a in client.get("/api/valuation").json()["assets"]}


def _asset_keys(client: TestClient, breakdown: str = "builtin:asset") -> set[str]:
    body = client.get("/api/shares", params={"breakdown": breakdown}).json()
    return {child["id"] for child in body["root"]["children"]}


def test_likely_pair_waits_for_the_owner_then_becomes_one_asset(client: TestClient) -> None:
    _xtb_and_bossa(client)
    assert client.get("/api/valuation").json()["link_suggestion_count"] == 1
    assert _asset_keys(client) == {ISAC, XTB_ATR, ATR_ISIN}  # not joined by itself

    (suggestion,) = client.get("/api/instruments").json()["suggestions"]
    assert (suggestion["key_a"], suggestion["key_b"]) == (ATR_ISIN, XTB_ATR)
    assert suggestion["reasons"] == ["ta sama nazwa", "podobna cena za sztukę"]

    body = _link(client, ATR_ISIN, XTB_ATR).json()

    assert body["suggestions"] == []
    by_key = {i["key"]: i for i in body["instruments"]}
    assert by_key[XTB_ATR]["asset_key"] == ATR_ISIN
    assert by_key[XTB_ATR]["linked_by"] == "owner"
    assert by_key[XTB_ATR]["asset_name"] == "Atrem"
    assert _asset_keys(client) == {ISAC, ATR_ISIN}
    atr = _assets(client)[ATR_ISIN]
    assert atr["quantity"] == "3.00000000"  # 1 at XTB + 2 at Bossa
    assert len(atr["position_ids"]) == 2
    assert atr["instrument_name"] == "Atrem"
    # Bossa's ledger has no instrument type; XTB's "STC" category says equity.
    assert atr["asset_class"] == "equity"
    assert client.get("/api/valuation").json()["link_suggestion_count"] == 0


def test_same_figi_joins_without_asking(client: TestClient) -> None:
    _xtb_and_bossa(client)
    # Both imports resolved to one listing (the stub-free way: straight in
    # the database, as an OpenFIGI-backed import would have stored it).
    client.app.state.db.execute(
        "UPDATE positions SET figi = 'BBG000ATREM' WHERE isin = ? OR symbol = 'ATR.PL'",
        [ATR_ISIN],
    )

    body = client.get("/api/instruments").json()

    assert body["suggestions"] == []
    by_key = {i["key"]: i for i in body["instruments"]}
    assert by_key[XTB_ATR]["linked_by"] == "figi"
    assert _asset_keys(client) == {ISAC, ATR_ISIN}


def test_answering_different_keeps_two_assets_and_stops_asking(client: TestClient) -> None:
    _xtb_and_bossa(client)

    body = _link(client, XTB_ATR, ATR_ISIN, same=False).json()

    assert body["suggestions"] == []
    assert _asset_keys(client) == {ISAC, XTB_ATR, ATR_ISIN}
    assert client.get("/api/valuation").json()["link_suggestion_count"] == 0


def test_breakdown_assignment_follows_the_asset(client: TestClient) -> None:
    _xtb_and_bossa(client)
    breakdown = client.post("/api/breakdowns", json={"name": "Strategia"}).json()
    groups = client.post(
        f"/api/breakdowns/{breakdown['id']}/groups", json={"name": "Akcje PL"}
    ).json()["groups"]
    client.post(f"/api/breakdowns/{breakdown['id']}/groups", json={"name": "Spekulacja"})
    stocks = groups[0]["id"]
    client.put(
        f"/api/breakdowns/{breakdown['id']}/assignments",
        json={"instrument_key": XTB_ATR, "group_id": stocks},
    )

    _link(client, ATR_ISIN, XTB_ATR)

    (listed,) = client.get("/api/breakdowns").json()
    assert listed["assignments"] == {ATR_ISIN: stocks}  # XTB's own assignment, now the asset's
    shares = client.get("/api/shares", params={"breakdown": breakdown["id"]}).json()
    group = next(c for c in shares["root"]["children"] if c["id"] == stocks)
    assert [c["id"] for c in group["children"]] == [ATR_ISIN]
    assert group["value"] == "159.30"  # 53.30 at XTB + 2 x 53.00 at Bossa

    speculation = next(g["id"] for g in listed["groups"] if g["name"] == "Spekulacja")
    moved = client.put(
        f"/api/breakdowns/{breakdown['id']}/assignments",
        json={"instrument_key": XTB_ATR, "group_id": speculation},
    ).json()
    assert moved["assignments"] == {ATR_ISIN: speculation}
    # The member's own row went with the move: detaching XTB again leaves it
    # unassigned instead of reviving the old group.
    client.post("/api/instruments/detach", json={"key": XTB_ATR})
    (after,) = client.get("/api/breakdowns").json()
    assert after["assignments"] == {ATR_ISIN: speculation}


def test_detaching_one_member_keeps_the_rest_joined(client: TestClient) -> None:
    xtb_id, _ = _xtb_and_bossa(client)
    manual = client.post(
        f"/api/portfolios/{xtb_id}/positions",
        json={"instrument_name": "Atrem (akcje pracownicze)", "asset_class": "equity",
              "quantity": "5", "avg_cost": "40"},
    ).json()  # fmt: skip
    manual_key = f"manual:{manual['id']}"
    _link(client, ATR_ISIN, XTB_ATR)
    _link(client, XTB_ATR, manual_key)  # the manual one joined only via XTB

    body = client.post("/api/instruments/detach", json={"key": XTB_ATR}).json()

    by_key = {i["key"]: i for i in body["instruments"]}
    assert by_key[XTB_ATR]["asset_key"] == XTB_ATR
    assert by_key[manual_key]["asset_key"] == ATR_ISIN
    # Detached means "different" -- it is not suggested straight back.
    assert body["suggestions"] == []


def test_link_requests_are_validated(client: TestClient) -> None:
    _xtb_and_bossa(client)

    assert _link(client, XTB_ATR, XTB_ATR).status_code == 422
    assert _link(client, XTB_ATR, "PLNOPE000000").status_code == 422
    detach = client.post("/api/instruments/detach", json={"key": "xtb:NOPE"})
    assert detach.status_code == 422
