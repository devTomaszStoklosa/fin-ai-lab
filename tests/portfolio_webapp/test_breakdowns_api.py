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
D = Decimal
# The synthetic XTB export: ISAC.UK worth 2745.41 PLN, ATR.PL 53.30 PLN.
ISAC, ATR = "xtb:ISAC.UK", "xtb:ATR.PL"


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


def _portfolio_with_import(client: TestClient, name: str = "XTB") -> str:
    portfolio_id = client.post(
        "/api/portfolios", json={"name": name, "broker": "xtb", "account_type": "regular"}
    ).json()["id"]
    response = client.post(
        f"/api/portfolios/{portfolio_id}/import",
        files={"file": ("p.xlsx", build_synthetic_xtb_workbook(), XLSX_CONTENT_TYPE)},
        data={"valuation_date": "2026-01-05"},
    )
    assert response.status_code == 201, response.text
    return portfolio_id


def _new_breakdown(client: TestClient, name: str = "Strategia") -> dict:
    response = client.post("/api/breakdowns", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _add_group(client: TestClient, breakdown_id: str, name: str, parent_id=None) -> dict:
    response = client.post(
        f"/api/breakdowns/{breakdown_id}/groups", json={"name": name, "parent_id": parent_id}
    )
    assert response.status_code == 201, response.text
    return next(g for g in response.json()["groups"] if g["name"] == name)


def _assign(client: TestClient, breakdown_id: str, key: str, group_id):
    return client.put(
        f"/api/breakdowns/{breakdown_id}/assignments",
        json={"instrument_key": key, "group_id": group_id},
    )


def _children(node: dict) -> dict[str, dict]:
    return {child["name"]: child for child in node["children"]}


def test_custom_breakdown_shares_nest_and_add_up(client: TestClient) -> None:
    _portfolio_with_import(client)
    breakdown = _new_breakdown(client)
    etf = _add_group(client, breakdown["id"], "ETF")
    stocks = _add_group(client, breakdown["id"], "Akcje")
    polish = _add_group(client, breakdown["id"], "Akcje PL", stocks["id"])
    assert _assign(client, breakdown["id"], ISAC, etf["id"]).status_code == 200
    _assign(client, breakdown["id"], ATR, polish["id"])

    body = client.get("/api/shares", params={"breakdown": breakdown["id"]}).json()

    assert body["breakdown_name"] == "Strategia"
    assert body["total_value"] == "2798.71"
    top = _children(body["root"])
    assert top["ETF"]["value"] == "2745.41"
    assert top["ETF"]["share_of_parent"] == "98.1"
    nested = _children(top["Akcje"])["Akcje PL"]
    assert nested["share_of_parent"] == "100.0"  # the only thing in "Akcje"
    assert nested["share_of_total"] == "1.9"
    assert top["Bez grupy"]["asset_count"] == 0


def test_instrument_can_sit_in_a_different_group_in_each_breakdown(client: TestClient) -> None:
    _portfolio_with_import(client)
    strategy, region = _new_breakdown(client, "Strategia"), _new_breakdown(client, "Region")
    etf = _add_group(client, strategy["id"], "ETF")
    uk = _add_group(client, region["id"], "Wielka Brytania")

    _assign(client, strategy["id"], ISAC, etf["id"])
    _assign(client, region["id"], ISAC, uk["id"])

    by_name = {b["name"]: b for b in client.get("/api/breakdowns").json()}
    assert by_name["Strategia"]["assignments"] == {ISAC: etf["id"]}
    assert by_name["Region"]["assignments"] == {ISAC: uk["id"]}


def test_reassigning_moves_instead_of_adding_a_second_group(client: TestClient) -> None:
    breakdown = _new_breakdown(client)
    a = _add_group(client, breakdown["id"], "A")
    b = _add_group(client, breakdown["id"], "B")

    _assign(client, breakdown["id"], ISAC, a["id"])
    body = _assign(client, breakdown["id"], ISAC, b["id"]).json()

    assert body["assignments"] == {ISAC: b["id"]}  # REQ-081: one group per instrument
    assert _assign(client, breakdown["id"], ISAC, None).json()["assignments"] == {}


def test_moving_a_group_into_its_own_subgroup_is_rejected(client: TestClient) -> None:
    breakdown = _new_breakdown(client)
    parent = _add_group(client, breakdown["id"], "Akcje")
    child = _add_group(client, breakdown["id"], "Akcje PL", parent["id"])

    response = client.put(
        f"/api/breakdowns/{breakdown['id']}/groups/{parent['id']}",
        json={"name": "Akcje", "parent_id": child["id"]},
    )

    assert response.status_code == 422
    assert "podgrupie" in response.json()["detail"]


def test_group_and_assignment_from_another_breakdown_are_rejected(client: TestClient) -> None:
    first, second = _new_breakdown(client, "A"), _new_breakdown(client, "B")
    foreign = _add_group(client, first["id"], "Obca")

    create = client.post(
        f"/api/breakdowns/{second['id']}/groups", json={"name": "X", "parent_id": foreign["id"]}
    )
    assign = _assign(client, second["id"], ISAC, foreign["id"])

    assert create.status_code == 422
    assert assign.status_code == 422


def test_deleting_a_group_moves_its_content_up(client: TestClient) -> None:
    breakdown = _new_breakdown(client)
    top = _add_group(client, breakdown["id"], "Akcje")
    middle = _add_group(client, breakdown["id"], "Akcje PL", top["id"])
    leaf = _add_group(client, breakdown["id"], "Banki", middle["id"])
    _assign(client, breakdown["id"], ATR, middle["id"])

    body = client.delete(f"/api/breakdowns/{breakdown['id']}/groups/{middle['id']}").json()

    groups = {g["name"]: g for g in body["groups"]}
    assert groups["Banki"]["parent_id"] == top["id"]  # subgroup moved up
    assert body["assignments"] == {ATR: top["id"]}  # instrument moved up
    assert leaf["id"] in {g["id"] for g in body["groups"]}

    top_level = client.delete(f"/api/breakdowns/{breakdown['id']}/groups/{top['id']}").json()
    assert top_level["assignments"] == {}  # top level: back to "Bez grupy"


def test_only_one_breakdown_is_default(client: TestClient) -> None:
    first, second = _new_breakdown(client, "A"), _new_breakdown(client, "B")

    client.put(f"/api/breakdowns/{first['id']}", json={"name": "A", "is_default": True})
    client.put(f"/api/breakdowns/{second['id']}", json={"name": "B2", "is_default": True})

    by_name = {b["name"]: b for b in client.get("/api/breakdowns").json()}
    assert by_name["A"]["is_default"] is False
    assert by_name["B2"]["is_default"] is True


def test_duplicate_copies_groups_and_assignments_under_new_ids(client: TestClient) -> None:
    source = _new_breakdown(client, "Strategia")
    parent = _add_group(client, source["id"], "Akcje")
    child = _add_group(client, source["id"], "Akcje PL", parent["id"])
    _assign(client, source["id"], ATR, child["id"])

    copy = client.post(f"/api/breakdowns/{source['id']}/duplicate").json()

    assert copy["name"] == "Strategia (kopia)"
    assert copy["is_default"] is False
    copied = {g["name"]: g for g in copy["groups"]}
    assert copied["Akcje PL"]["parent_id"] == copied["Akcje"]["id"] != parent["id"]
    assert copy["assignments"] == {ATR: copied["Akcje PL"]["id"]}


def test_deleting_a_breakdown_removes_it(client: TestClient) -> None:
    breakdown = _new_breakdown(client)

    assert client.delete(f"/api/breakdowns/{breakdown['id']}").status_code == 204
    assert client.get("/api/breakdowns").json() == []
    assert client.delete(f"/api/breakdowns/{breakdown['id']}").status_code == 404


def test_builtin_shares_need_no_setup(client: TestClient) -> None:
    portfolio_id = _portfolio_with_import(client)

    body = client.get(
        "/api/shares", params={"breakdown": "builtin:asset_class", "portfolio_id": portfolio_id}
    ).json()

    assert body["breakdown_name"] == "Klasa aktywów"
    assert body["root"]["name"] == "XTB"
    assert [(c["name"], c["share_of_parent"]) for c in body["root"]["children"]] == [
        ("Akcje", "1.9"),
        ("ETF", "98.1"),
    ]


def test_all_portfolios_scope_sums_every_portfolio(client: TestClient) -> None:
    _portfolio_with_import(client, "XTB zwykły")
    _portfolio_with_import(client, "XTB IKE")

    body = client.get("/api/shares", params={"breakdown": "builtin:portfolio"}).json()

    assert body["root"]["name"] == "Wszystkie portfele"
    assert body["total_value"] == "5597.42"
    assert [c["share_of_parent"] for c in body["root"]["children"]] == ["50.0", "50.0"]
    # Same instruments in both XTB portfolios: one asset each in a breakdown.
    per_asset = client.get("/api/shares", params={"breakdown": "builtin:asset"}).json()
    assert {c["id"] for c in per_asset["root"]["children"]} == {ISAC, ATR}


def test_unknown_breakdowns_and_portfolios_are_rejected(client: TestClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"

    assert client.get("/api/shares", params={"breakdown": "builtin:nope"}).status_code == 422
    assert client.get("/api/shares", params={"breakdown": "nope"}).status_code == 422
    assert client.get("/api/shares", params={"breakdown": missing}).status_code == 404
    assert client.get("/api/shares", params={"portfolio_id": missing}).status_code == 404
