from pathlib import Path

import httpx
import pytest
from google.genai import errors, types

from fin_ai_lab.core.llm.client import (
    DEFAULT_RETRY_OPTIONS,
    GeminiLlmClient,
    LlmRequest,
)
from fin_ai_lab.core.llm.trace import TraceSink

_OK_BODY = {
    "candidates": [
        {"content": {"role": "model", "parts": [{"text": "ok"}]}, "finishReason": "STOP"}
    ],
    "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1},
}
_FAST_RETRY = types.HttpRetryOptions(
    attempts=4, initial_delay=0.001, max_delay=0.01, http_status_codes=[500, 502, 503, 504]
)


def _client(handler, tmp_path: Path) -> GeminiLlmClient:
    return GeminiLlmClient(
        api_key="test-key",
        trace_sink=TraceSink(tmp_path),
        retry_options=_FAST_RETRY,
        httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _request() -> LlmRequest:
    return LlmRequest(model="gemini-3.6-flash", messages=[{"role": "user", "text": "hi"}])


async def test_complete_retries_a_transient_503_then_succeeds(tmp_path: Path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503, json={"error": {"code": 503, "status": "UNAVAILABLE"}})
        return httpx.Response(200, json=_OK_BODY)

    result = await _client(handler, tmp_path).complete(_request())

    assert result.text == "ok"
    assert len(calls) == 3


async def test_complete_gives_up_after_the_bounded_attempts(tmp_path: Path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, json={"error": {"code": 503, "status": "UNAVAILABLE"}})

    with pytest.raises(errors.ServerError):
        await _client(handler, tmp_path).complete(_request())

    assert len(calls) == 4


async def test_complete_does_not_retry_a_429(tmp_path: Path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, json={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}})

    with pytest.raises(errors.ClientError):
        await _client(handler, tmp_path).complete(_request())

    assert len(calls) == 1


def test_default_retry_options_cover_transient_5xx_but_not_429() -> None:
    assert 503 in DEFAULT_RETRY_OPTIONS.http_status_codes
    assert 429 not in DEFAULT_RETRY_OPTIONS.http_status_codes
