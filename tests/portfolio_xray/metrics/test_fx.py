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


async def test_mid_rate_series_for_pln_needs_no_request(tmp_path: Path) -> None:
    client = _client(lambda request: httpx.Response(500), tmp_path)  # should never be called

    assert await client.mid_rate_series("PLN", date(2026, 1, 1), date(2026, 3, 1)) == {}


async def test_mid_rate_series_splits_range_into_windows_nbp_accepts(tmp_path: Path) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        # .../rates/a/usd/<window start>/<window end>/
        window_start, window_end = request.url.path.rstrip("/").split("/")[-2:]
        return httpx.Response(
            200,
            json={
                "rates": [
                    {"effectiveDate": window_start, "mid": 4.0},
                    {"effectiveDate": window_end, "mid": 4.1},
                ]
            },
        )

    client = _client(handler, tmp_path)

    rates = await client.mid_rate_series("USD", date(2026, 1, 1), date(2026, 9, 1))

    assert len(paths) >= 3
    for path in paths:
        window_start, window_end = (
            date.fromisoformat(part) for part in path.rstrip("/").split("/")[-2:]
        )
        assert (window_end - window_start).days < 93  # NBP's own per-query limit
    # Rates outside the requested range are dropped even if a window returns them.
    assert all(date(2026, 1, 1) <= day <= date(2026, 9, 1) for day in rates)
    assert rates[date(2026, 9, 1)] == Decimal("4.1")


async def test_mid_rate_series_treats_404_window_as_empty(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/rates/a/" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200, json={"rates": [{"effectiveDate": "2026-01-05", "mid": 1.5}]})

    client = _client(handler, tmp_path)

    rates = await client.mid_rate_series("XYZ", date(2026, 1, 1), date(2026, 1, 10))

    # Table A had nothing at all -> falls back to table B, like mid_rate.
    assert rates == {date(2026, 1, 5): Decimal("1.5")}


async def test_mid_rate_series_raises_when_no_table_has_the_currency(tmp_path: Path) -> None:
    client = _client(lambda request: httpx.Response(404), tmp_path)

    with pytest.raises(FxRateNotFoundError):
        await client.mid_rate_series("XYZ", date(2026, 1, 1), date(2026, 1, 10))
