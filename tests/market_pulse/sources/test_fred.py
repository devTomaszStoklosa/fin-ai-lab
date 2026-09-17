from decimal import Decimal
from pathlib import Path

import httpx

from fin_ai_lab.core.http.client import ThrottledHttpClient
from fin_ai_lab.market_pulse.sources.fred import FredClient


def _client(tmp_path: Path, handler: httpx.MockTransport) -> FredClient:
    http_client = ThrottledHttpClient(
        "https://api.stlouisfed.org",
        min_interval_s=0.0,
        provider="fred-test",
        cache_dir=tmp_path,
        transport=handler,
    )
    return FredClient("fake-key", http_client=http_client)


async def test_latest_observation_returns_the_most_recent_value(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"observations": [{"date": "2026-09-15", "value": "5.0"}]},
        )

    client = _client(tmp_path, httpx.MockTransport(handler))

    result = await client.latest_observation("DGS10")

    assert result is not None
    value, as_of = result
    assert value == Decimal("5.0")
    assert as_of.isoformat() == "2026-09-15"


async def test_latest_observation_returns_none_for_a_missing_value(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"observations": [{"date": "2026-09-15", "value": "."}]})

    client = _client(tmp_path, httpx.MockTransport(handler))

    result = await client.latest_observation("DGS10")

    assert result is None


async def test_latest_observation_returns_none_when_no_observations(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"observations": []})

    client = _client(tmp_path, httpx.MockTransport(handler))

    result = await client.latest_observation("DGS10")

    assert result is None
