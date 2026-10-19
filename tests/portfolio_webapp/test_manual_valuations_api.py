import uuid
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from fin_ai_lab.portfolio_webapp.api import create_app  # noqa: E402

TODAY = date(2026, 10, 18)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(
        db_path=tmp_path / "test.duckdb",
        openfigi_client_factory=lambda: None,
        price_ratio_fetcher=lambda ticker, since: None,
        quote_currency_fetcher=lambda ticker: None,
        today_provider=lambda: TODAY,
    )
    with TestClient(app) as test_client:
        yield test_client


def _portfolio(client: TestClient) -> str:
    response = client.post("/api/portfolios", json={"name": "Skarbiec", "account_type": "regular"})
    return response.json()["id"]


def _coin_payload(**overrides: object) -> dict:
    # #288's own example: two gold coins bought for 9000 PLN each.
    return {
        "instrument_name": "Krugerrand 1 oz",
        "asset_class": "other",
        "quantity": "2",
        "avg_cost": "9000",
        "purchased_on": "2026-03-10",
    } | overrides


def _coin(client: TestClient, portfolio_id: str, **overrides: object) -> dict:
    response = client.post(
        f"/api/portfolios/{portfolio_id}/positions", json=_coin_payload(**overrides)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _valuations(portfolio_id: str, position_id: str) -> str:
    return f"/api/portfolios/{portfolio_id}/positions/{position_id}/valuations"


def _stored_value(client: TestClient, portfolio_id: str) -> str:
    (position,) = client.get(f"/api/portfolios/{portfolio_id}/positions").json()
    return position["market_value"]


def _valuation_rows(client: TestClient) -> int:
    return client.app.state.db.execute("SELECT count(*) FROM manual_valuations").fetchone()[0]


def test_create_dates_the_position_on_its_purchase_date(client: TestClient) -> None:
    portfolio_id = _portfolio(client)

    body = _coin(client, portfolio_id)

    assert body["valuation_date"] == "2026-03-10"
    assert body["market_value"] == "18000.00000000"  # valued at cost: no valuation yet


def test_create_without_purchase_date_dates_it_today(client: TestClient) -> None:
    portfolio_id = _portfolio(client)
    payload = _coin_payload()
    del payload["purchased_on"]

    response = client.post(f"/api/portfolios/{portfolio_id}/positions", json=payload)

    assert response.json()["valuation_date"] == "2026-10-18"


def test_create_with_a_future_purchase_date_is_refused(client: TestClient) -> None:
    portfolio_id = _portfolio(client)

    response = client.post(
        f"/api/portfolios/{portfolio_id}/positions", json=_coin_payload(purchased_on="2026-10-19")
    )

    assert response.status_code == 422
    assert "przyszłości" in response.json()["detail"]


def test_valuations_move_the_value_and_list_by_day(client: TestClient) -> None:
    portfolio_id = _portfolio(client)
    coin = _coin(client, portfolio_id)
    url = _valuations(portfolio_id, coin["id"])

    saved = client.put(f"{url}/2026-09-01", json={"unit_value": "11000"})
    client.put(f"{url}/2026-06-01", json={"unit_value": "10000"})

    assert saved.status_code == 200
    assert saved.json() == {"valued_on": "2026-09-01", "unit_value": "11000", "value": "22000.00"}
    listed = client.get(url).json()
    assert [(v["valued_on"], v["value"]) for v in listed] == [
        ("2026-06-01", "20000.00"),
        ("2026-09-01", "22000.00"),
    ]
    assert _stored_value(client, portfolio_id) == "22000.00000000"  # the latest one


def test_second_valuation_of_the_same_day_replaces_the_first(client: TestClient) -> None:
    portfolio_id = _portfolio(client)
    coin = _coin(client, portfolio_id)
    url = _valuations(portfolio_id, coin["id"])

    client.put(f"{url}/2026-09-01", json={"unit_value": "11000"})
    client.put(f"{url}/2026-09-01", json={"unit_value": "10500"})

    assert [v["unit_value"] for v in client.get(url).json()] == ["10500.00000000"]
    assert _stored_value(client, portfolio_id) == "21000.00000000"


@pytest.mark.parametrize("day", ["2026-03-09", "2026-10-19"])
def test_valuation_before_purchase_or_in_the_future_is_refused(
    client: TestClient, day: str
) -> None:
    portfolio_id = _portfolio(client)
    coin = _coin(client, portfolio_id)

    response = client.put(
        f"{_valuations(portfolio_id, coin['id'])}/{day}", json={"unit_value": "11000"}
    )

    assert response.status_code == 422
    assert _valuation_rows(client) == 0


def test_negative_valuation_is_refused(client: TestClient) -> None:
    portfolio_id = _portfolio(client)
    coin = _coin(client, portfolio_id)

    response = client.put(
        f"{_valuations(portfolio_id, coin['id'])}/2026-09-01", json={"unit_value": "-1"}
    )

    assert response.status_code == 422


def test_deleting_valuations_falls_back_to_the_previous_then_to_cost(client: TestClient) -> None:
    portfolio_id = _portfolio(client)
    coin = _coin(client, portfolio_id)
    url = _valuations(portfolio_id, coin["id"])
    client.put(f"{url}/2026-06-01", json={"unit_value": "10000"})
    client.put(f"{url}/2026-09-01", json={"unit_value": "11000"})

    assert client.delete(f"{url}/2026-09-01").status_code == 204
    assert _stored_value(client, portfolio_id) == "20000.00000000"
    assert client.delete(f"{url}/2026-06-01").status_code == 204
    assert _stored_value(client, portfolio_id) == "18000.00000000"


def test_deleting_a_missing_valuation_returns_404(client: TestClient) -> None:
    portfolio_id = _portfolio(client)
    coin = _coin(client, portfolio_id)

    response = client.delete(f"{_valuations(portfolio_id, coin['id'])}/2026-09-01")

    assert response.status_code == 404


def test_valuations_of_an_unknown_position_return_404(client: TestClient) -> None:
    portfolio_id = _portfolio(client)
    url = _valuations(portfolio_id, str(uuid.uuid4()))

    assert client.get(url).status_code == 404
    assert client.put(f"{url}/2026-09-01", json={"unit_value": "1"}).status_code == 404


def test_purchase_date_cannot_move_past_the_earliest_valuation(client: TestClient) -> None:
    portfolio_id = _portfolio(client)
    coin = _coin(client, portfolio_id)
    client.put(f"{_valuations(portfolio_id, coin['id'])}/2026-06-01", json={"unit_value": "10000"})
    position_url = f"/api/portfolios/{portfolio_id}/positions/{coin['id']}"

    refused = client.put(position_url, json=_coin_payload(purchased_on="2026-07-01"))
    moved = client.put(position_url, json=_coin_payload(purchased_on="2026-05-01"))

    assert refused.status_code == 422
    assert "2026-06-01" in refused.json()["detail"]
    assert moved.status_code == 200
    assert moved.json()["valuation_date"] == "2026-05-01"


def test_update_follows_valuations_and_keeps_an_omitted_purchase_date(client: TestClient) -> None:
    portfolio_id = _portfolio(client)
    coin = _coin(client, portfolio_id)
    client.put(f"{_valuations(portfolio_id, coin['id'])}/2026-06-01", json={"unit_value": "10000"})
    payload = _coin_payload(quantity="3")
    del payload["purchased_on"]

    response = client.put(f"/api/portfolios/{portfolio_id}/positions/{coin['id']}", json=payload)

    body = response.json()
    assert body["valuation_date"] == "2026-03-10"
    assert body["market_value"] == "30000.00000000"  # 3 x the 10000 valuation, per unit
    assert body["return_pct"] == "11.1"  # (30000 - 27000) / 27000


def test_deleting_the_position_or_its_portfolio_removes_its_valuations(client: TestClient) -> None:
    portfolio_id = _portfolio(client)
    first = _coin(client, portfolio_id)
    second = _coin(client, portfolio_id, instrument_name="Wiedeński Filharmonik")
    for coin in (first, second):
        client.put(f"{_valuations(portfolio_id, coin['id'])}/2026-06-01", json={"unit_value": "1"})

    client.delete(f"/api/portfolios/{portfolio_id}/positions/{first['id']}")
    assert _valuation_rows(client) == 1
    client.delete(f"/api/portfolios/{portfolio_id}")
    assert _valuation_rows(client) == 0
