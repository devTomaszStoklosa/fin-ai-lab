from pathlib import Path

import httpx

from fin_ai_lab.core.http.client import ThrottledHttpClient
from fin_ai_lab.portfolio_xray.identification.openfigi import OpenFigiClient


def _client_with_response(response_body: object, tmp_path: Path, seen: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen["headers"] = request.headers
        return httpx.Response(200, json=response_body)

    http_client = ThrottledHttpClient(
        base_url="https://api.openfigi.test",
        min_interval_s=0.0,
        provider="openfigi-test",
        cache_dir=tmp_path,
        transport=httpx.MockTransport(handler),
    )
    return OpenFigiClient(http_client=http_client)


async def test_resolve_by_isin_returns_unresolved_on_no_match(tmp_path: Path) -> None:
    client = _client_with_response([{"warning": "No identifier found."}], tmp_path)

    identification = await client.resolve_by_isin("US0378331005", "USD")

    assert identification.status == "unresolved"


async def test_resolve_by_isin_returns_resolved_for_single_match(tmp_path: Path) -> None:
    match = {"figi": "BBG1", "ticker": "AAPL", "exchCode": "US", "securityType": "Common Stock"}
    client = _client_with_response([{"data": [match]}], tmp_path)

    identification = await client.resolve_by_isin("US0378331005", "USD")

    assert identification.status == "resolved"
    assert identification.figi == "BBG1"
    assert identification.identification_rule == "only listing in currency"


async def test_resolve_by_isin_picks_broker_market_when_ambiguous(tmp_path: Path) -> None:
    client = _client_with_response(
        [
            {
                "data": [
                    {"figi": "BBG1", "ticker": "X", "exchCode": "US"},
                    {"figi": "BBG2", "ticker": "X", "exchCode": "GR"},
                ]
            }
        ],
        tmp_path,
    )

    identification = await client.resolve_by_isin("US0378331005", "USD", broker_market="GR")

    assert identification.status == "resolved"
    assert identification.figi == "BBG2"
    assert identification.identification_rule == "broker market"


async def test_resolve_by_isin_is_ambiguous_without_broker_market(tmp_path: Path) -> None:
    client = _client_with_response(
        [{"data": [{"figi": "BBG1", "exchCode": "US"}, {"figi": "BBG2", "exchCode": "GR"}]}],
        tmp_path,
    )

    identification = await client.resolve_by_isin("US0378331005", "USD")

    assert identification.status == "ambiguous"


async def test_resolve_by_isin_ambiguous_when_broker_market_matches_none(tmp_path: Path) -> None:
    client = _client_with_response(
        [{"data": [{"figi": "BBG1", "exchCode": "US"}, {"figi": "BBG2", "exchCode": "GR"}]}],
        tmp_path,
    )

    identification = await client.resolve_by_isin("US0378331005", "USD", broker_market="FR")

    assert identification.status == "ambiguous"


async def test_api_key_is_sent_as_header_when_provided(tmp_path: Path) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("X-OPENFIGI-APIKEY")
        return httpx.Response(200, json=[{"warning": "No identifier found."}])

    http_client = ThrottledHttpClient(
        base_url="https://api.openfigi.test",
        min_interval_s=0.0,
        provider="openfigi-test-key",
        cache_dir=tmp_path,
        default_headers={"Content-Type": "application/json", "X-OPENFIGI-APIKEY": "abc"},
        transport=httpx.MockTransport(handler),
    )
    client = OpenFigiClient(http_client=http_client)

    await client.resolve_by_isin("US0378331005", "USD")

    assert seen["key"] == "abc"
