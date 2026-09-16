from pathlib import Path

import httpx
import pytest

from fin_ai_lab.core.http.client import ThrottledHttpClient


def _client(handler, tmp_path: Path, **overrides) -> ThrottledHttpClient:
    kwargs = dict(
        base_url="https://example.test",
        min_interval_s=0.0,
        provider="test",
        cache_dir=tmp_path,
        retry_backoff_base_s=0.001,
        transport=httpx.MockTransport(handler),
    )
    kwargs.update(overrides)
    return ThrottledHttpClient(**kwargs)


async def test_get_returns_parsed_json(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client = _client(handler, tmp_path)

    result = await client.get("/thing", params={"a": "1"})

    assert result == {"ok": True}


async def test_post_sends_json_body_and_default_headers(tmp_path: Path) -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        seen["header"] = request.headers.get("X-Api-Key")
        return httpx.Response(200, json=[{"data": []}])

    client = _client(handler, tmp_path, default_headers={"X-Api-Key": "secret"})

    result = await client.post("/mapping", json_body=[{"idType": "ID_ISIN"}])

    assert result == [{"data": []}]
    assert seen["header"] == "secret"
    assert b"ID_ISIN" in seen["body"]


async def test_repeated_request_is_served_from_cache_without_a_second_call(tmp_path: Path) -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json={"count": call_count["n"]})

    client = _client(handler, tmp_path)

    first = await client.get("/thing")
    second = await client.get("/thing")

    assert first == second == {"count": 1}
    assert call_count["n"] == 1


async def test_no_result_response_is_cached_too(tmp_path: Path) -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json=[{"warning": "No identifier found."}])

    client = _client(handler, tmp_path)

    await client.post("/mapping", json_body=[{"idType": "ID_ISIN"}])
    await client.post("/mapping", json_body=[{"idType": "ID_ISIN"}])

    assert call_count["n"] == 1


async def test_retries_on_429_then_succeeds(tmp_path: Path) -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 2:
            return httpx.Response(429)
        return httpx.Response(200, json={"ok": True})

    client = _client(handler, tmp_path)

    result = await client.get("/thing")

    assert result == {"ok": True}
    assert attempts["n"] == 2


async def test_raises_after_exhausting_retries_on_persistent_500(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = _client(handler, tmp_path)

    with pytest.raises(httpx.HTTPStatusError):
        await client.get("/thing")


async def test_get_text_returns_raw_body_and_caches_without_a_second_call(tmp_path: Path) -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, text="<html><body>Item 1A. Risk Factors</body></html>")

    client = _client(handler, tmp_path)

    first = await client.get_text("/filing.htm")
    second = await client.get_text("/filing.htm")

    assert first == second == "<html><body>Item 1A. Risk Factors</body></html>"
    assert call_count["n"] == 1


async def test_different_requests_use_different_cache_entries(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"path": request.url.path})

    client = _client(handler, tmp_path)

    first = await client.get("/a")
    second = await client.get("/b")

    assert first != second
