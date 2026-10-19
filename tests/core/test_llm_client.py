import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest
from google.genai import errors, types

from fin_ai_lab.core.llm.client import (
    DEFAULT_MIN_INTERVAL_S,
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


def _client(handler, tmp_path: Path, min_interval_s: float = 0.0) -> GeminiLlmClient:
    return GeminiLlmClient(
        api_key="test-key",
        trace_sink=TraceSink(tmp_path),
        retry_options=_FAST_RETRY,
        httpx_async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        min_interval_s=min_interval_s,
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


def test_default_min_interval_s_matches_gemini_3_6_flashs_free_tier_rpm() -> None:
    # quotaValue: 5 (GenerateRequestsPerMinutePerProjectPerModel-FreeTier),
    # verified live via a real 429 -- issue #218.
    assert DEFAULT_MIN_INTERVAL_S == pytest.approx(12.0)


async def test_complete_spaces_out_two_sequential_calls(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_OK_BODY)

    client = _client(handler, tmp_path, min_interval_s=0.1)

    started = time.monotonic()
    await client.complete(_request())
    await client.complete(_request())
    elapsed = time.monotonic() - started

    # Slack below the nominal 0.1s: proves throttling happened (an
    # unthrottled pair would take ~0s) without flaking under system jitter.
    assert elapsed >= 0.08


async def test_complete_serializes_concurrent_gather_callers(tmp_path: Path) -> None:
    # The exact shape of issue #218: run_committee dispatches several
    # complete() calls via asyncio.gather -- the throttle must space those
    # out too, not just calls that already happen to be sequential.
    call_times: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        call_times.append(time.monotonic())
        return httpx.Response(200, json=_OK_BODY)

    client = _client(handler, tmp_path, min_interval_s=0.1)

    started = time.monotonic()
    await asyncio.gather(*(client.complete(_request()) for _ in range(3)))

    # Slack below the nominal 0.2s (two waits of 0.1s) -- same reasoning as
    # the sequential test above.
    assert len(call_times) == 3
    assert call_times[-1] - started >= 0.18


def _spans(tmp_path: Path) -> list[dict]:
    return [
        json.loads(line)
        for path in tmp_path.glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def test_default_retry_options_allow_one_retry() -> None:
    # #254: every attempt counts against the 20-a-day free-tier cap.
    assert DEFAULT_RETRY_OPTIONS.attempts == 2


async def test_complete_records_each_http_attempt_in_its_trace_span(tmp_path: Path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": {"code": 503, "status": "UNAVAILABLE"}})
        return httpx.Response(200, json=_OK_BODY)

    await _client(handler, tmp_path).complete(_request())

    assert [span["attempts"] for span in _spans(tmp_path)] == [2]


async def test_a_failed_call_records_every_attempt_it_made(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"code": 503, "status": "UNAVAILABLE"}})

    with pytest.raises(errors.ServerError):
        await _client(handler, tmp_path).complete(_request())

    spans = _spans(tmp_path)
    assert spans[0]["attempts"] == 4
    assert spans[0]["error"].startswith("ServerError")


async def test_a_retry_waits_for_the_throttle_like_any_other_request(tmp_path: Path) -> None:
    # The exact shape of #254: the SDK's own retry used to go out within
    # seconds, bypassing the per-minute spacing.
    request_times: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_times.append(time.monotonic())
        if len(request_times) == 1:
            return httpx.Response(503, json={"error": {"code": 503, "status": "UNAVAILABLE"}})
        return httpx.Response(200, json=_OK_BODY)

    await _client(handler, tmp_path, min_interval_s=0.1).complete(_request())

    assert len(request_times) == 2
    assert request_times[1] - request_times[0] >= 0.08


async def test_concurrent_calls_count_only_their_own_attempts(tmp_path: Path) -> None:
    failed_once = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal failed_once
        if b"retry me" in request.content and not failed_once:
            failed_once = True
            return httpx.Response(503, json={"error": {"code": 503, "status": "UNAVAILABLE"}})
        return httpx.Response(200, json=_OK_BODY)

    client = _client(handler, tmp_path)
    await asyncio.gather(
        client.complete(
            LlmRequest(
                model="gemini-3.6-flash",
                messages=[{"role": "user", "text": "retry me"}],
                prompt_id="flaky",
            )
        ),
        client.complete(
            LlmRequest(
                model="gemini-3.6-flash",
                messages=[{"role": "user", "text": "fine"}],
                prompt_id="steady",
            )
        ),
    )

    attempts = {span["prompt_id"]: span["attempts"] for span in _spans(tmp_path)}
    assert attempts == {"flaky": 2, "steady": 1}


def _lookup_rate() -> str:
    """Returns the current rate."""
    return "5%"


async def test_each_automatic_function_calling_turn_counts_as_an_attempt(tmp_path: Path) -> None:
    # One complete() with tools sends one request per tool-use turn, all
    # inside the SDK -- each counts against Gemini's quota.
    tool_call_body = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"functionCall": {"name": "_lookup_rate", "args": {}}}],
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1},
    }
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=tool_call_body if len(calls) == 1 else _OK_BODY)

    request = LlmRequest(
        model="gemini-3.6-flash",
        messages=[{"role": "user", "text": "rate?"}],
        tools=[_lookup_rate],
    )
    result = await _client(handler, tmp_path).complete(request)

    assert result.tool_calls == ["_lookup_rate"]
    assert len(calls) == 2
    assert [span["attempts"] for span in _spans(tmp_path)] == [2]
