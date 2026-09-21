from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from fin_ai_lab.portfolio_webapp.api import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(db_path=tmp_path / "test.duckdb")
    with TestClient(app) as test_client:
        yield test_client


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_portfolios_starts_empty(client: TestClient) -> None:
    response = client.get("/api/portfolios")

    assert response.status_code == 200
    assert response.json() == []


def test_create_portfolio_then_appears_in_list(client: TestClient) -> None:
    create_response = client.post(
        "/api/portfolios",
        json={"name": "XTB — Rachunek zwykły", "broker": "xtb", "account_type": "regular"},
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["name"] == "XTB — Rachunek zwykły"
    assert created["broker"] == "xtb"

    list_response = client.get("/api/portfolios")
    assert [p["id"] for p in list_response.json()] == [created["id"]]


def test_create_portfolio_rejects_empty_name(client: TestClient) -> None:
    response = client.post("/api/portfolios", json={"name": ""})

    assert response.status_code == 422
