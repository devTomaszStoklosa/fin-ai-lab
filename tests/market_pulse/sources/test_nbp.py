from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from fin_ai_lab.core.http.client import ThrottledHttpClient
from fin_ai_lab.market_pulse.sources.nbp import NbpClient, fetch_reference_rate


def _fx_client(tmp_path: Path, handler: httpx.MockTransport) -> NbpClient:
    http_client = ThrottledHttpClient(
        "https://api.nbp.pl",
        min_interval_s=0.0,
        provider="nbp-fx-test",
        cache_dir=tmp_path,
        transport=handler,
    )
    return NbpClient(fx_http_client=http_client)


async def test_fetch_fx_rate_returns_todays_rate_when_published(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/exchangerates/rates/a/eur/2026-09-17/"
        return httpx.Response(
            200, json={"rates": [{"mid": 4.36, "effectiveDate": "2026-09-17"}]}
        )

    client = _fx_client(tmp_path, httpx.MockTransport(handler))

    result = await client.fetch_fx_rate("EUR", as_of=date(2026, 9, 17))

    assert result is not None
    value, as_of = result
    assert value == Decimal("4.36")
    assert as_of == date(2026, 9, 17)


async def test_fetch_fx_rate_walks_back_over_a_weekend(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/2026-09-17/"):
            return httpx.Response(404, json={"error": "not found"})
        if request.url.path.endswith("/2026-09-16/"):
            return httpx.Response(
                200, json={"rates": [{"mid": 4.35, "effectiveDate": "2026-09-16"}]}
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    client = _fx_client(tmp_path, httpx.MockTransport(handler))

    result = await client.fetch_fx_rate("EUR", as_of=date(2026, 9, 17))

    assert result is not None
    value, as_of = result
    assert value == Decimal("4.35")
    assert as_of == date(2026, 9, 16)


async def test_fetch_fx_rate_returns_none_when_nothing_published_in_lookback_window(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    client = _fx_client(tmp_path, httpx.MockTransport(handler))

    result = await client.fetch_fx_rate("EUR", as_of=date(2026, 9, 17))

    assert result is None


async def test_fetch_fx_rate_reraises_a_non_404_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = _fx_client(tmp_path, httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPStatusError):
        await client.fetch_fx_rate("EUR", as_of=date(2026, 9, 17))


async def test_fetch_reference_rate_parses_the_real_xml_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xml_body = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<stopy_procentowe data_publikacji="2026-03-05">'
        b'<tabela id="stoproc"><pozycja id="ref" nazwa="Stopa referencyjna" '
        b'oprocentowanie="3,75" obowiazuje_od="2026-03-05"/></tabela></stopy_procentowe>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=xml_body)

    import fin_ai_lab.market_pulse.sources.nbp as nbp_module

    original_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(nbp_module.httpx, "AsyncClient", fake_async_client)

    value, as_of = await fetch_reference_rate()

    assert value == Decimal("3.75")
    assert as_of == date(2026, 3, 5)
