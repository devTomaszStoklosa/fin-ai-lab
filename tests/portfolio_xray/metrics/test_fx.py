from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from fin_ai_lab.core.http.client import ThrottledHttpClient
from fin_ai_lab.portfolio_xray.metrics.fx import FxRateNotFoundError, NbpFxClient


def _client(handler, tmp_path: Path) -> NbpFxClient:
    http_client = ThrottledHttpClient(
        base_url="https://api.nbp.test",
        min_interval_s=0.0,
        provider="nbp-test",
        cache_dir=tmp_path,
        retry_backoff_base_s=0.001,
        transport=httpx.MockTransport(handler),
    )
    return NbpFxClient(http_client=http_client)


async def test_pln_is_always_rate_one(tmp_path: Path) -> None:
    client = _client(lambda request: httpx.Response(500), tmp_path)  # should never be called

    rate = await client.mid_rate("PLN", date(2026, 9, 15))

    assert rate == Decimal(1)


async def test_returns_mid_rate_from_table_a(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/rates/a/usd/" in request.url.path
        return httpx.Response(200, json={"rates": [{"mid": 4.05}]})

    client = _client(handler, tmp_path)

    rate = await client.mid_rate("USD", date(2026, 9, 15))

    assert rate == Decimal("4.05")


async def test_falls_back_to_previous_day_when_no_table(tmp_path: Path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/2026-09-15/"):
            return httpx.Response(404)
        return httpx.Response(200, json={"rates": [{"mid": 4.0}]})

    client = _client(handler, tmp_path)

    rate = await client.mid_rate("USD", date(2026, 9, 15))

    assert rate == Decimal("4.0")
    assert any(c.endswith("/2026-09-14/") for c in calls)


async def test_falls_back_to_table_b_when_currency_not_in_table_a(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/rates/a/" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200, json={"rates": [{"mid": 1.5}]})

    client = _client(handler, tmp_path)

    rate = await client.mid_rate("XYZ", date(2026, 9, 15))

    assert rate == Decimal("1.5")


async def test_raises_when_no_table_has_the_currency(tmp_path: Path) -> None:
    client = _client(lambda request: httpx.Response(404), tmp_path)

    with pytest.raises(FxRateNotFoundError):
        await client.mid_rate("ZZZ", date(2026, 9, 15))
