import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

import httpx
from google import genai
from google.genai import types
from pydantic import BaseModel

from fin_ai_lab.core.errors import ResponseValidationError, UnknownModelError
from fin_ai_lab.core.llm.pricing import PRICES
from fin_ai_lab.core.llm.trace import TraceSink, TraceSpan


class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int


class LlmRequest(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    model: str
    messages: list[dict]
    system_instruction: str | None = None
    max_output_tokens: int = 16_000
    response_schema: type[BaseModel] | None = None
    # Plain Python (sync or async) callables — the SDK's own automatic
    # function calling (AFC) derives each tool's schema from its signature
    # and docstring, invokes the ones the model picks, and loops until a
    # final text answer, all inside this one complete() call (P3-S2,
    # 03-design.md). Known trade-off, accepted: AFC's returned response
    # only carries usage_metadata for its last internal turn, so cost_usd
    # below undercounts whenever the model makes more than one tool call —
    # not a correctness requirement for this feature (user decision).
    tools: list[Callable] | None = None
    prompt_id: str | None = None
    prompt_version: int | None = None


class LlmResult(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    text: str
    parsed: BaseModel | None
    finish_reason: str
    incomplete: bool
    usage: TokenUsage
    cost_usd: Decimal
    latency_ms: int
    trace_id: str
    span_id: str
    # Names of tools the model called during automatic function calling
    # (P3-S2), in order — read from the SDK's own
    # automatic_function_calling_history (verified live against the
    # installed SDK, not guessed). Needed for P3-S8's trajectory eval
    # ("did the agent call the right tools"), not just cost/text.
    tool_calls: list[str] = []


class LlmClient(Protocol):
    async def complete(self, request: LlmRequest) -> LlmResult: ...


def _to_contents(messages: list[dict]) -> list[types.ContentDict]:
    return [{"role": m["role"], "parts": [{"text": m["text"]}]} for m in messages]


# Transient server-side errors only. 429 is deliberately excluded: the free
# tier's daily cap (docs/LLM-API.md) does not clear within seconds, so
# retrying it just burns time (and possibly quota).
DEFAULT_RETRY_OPTIONS = types.HttpRetryOptions(
    attempts=4,
    initial_delay=2.0,
    max_delay=30.0,
    http_status_codes=[500, 502, 503, 504],
)


class GeminiLlmClient:
    def __init__(
        self,
        api_key: str,
        trace_sink: TraceSink | None = None,
        *,
        retry_options: types.HttpRetryOptions = DEFAULT_RETRY_OPTIONS,
        httpx_async_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                retry_options=retry_options, httpx_async_client=httpx_async_client
            ),
        )
        self._trace_sink = trace_sink or TraceSink()
        self.total_cost_usd = Decimal(0)

    async def complete(self, request: LlmRequest) -> LlmResult:
        price = PRICES.get(request.model)
        if price is None:
            raise UnknownModelError(request.model)

        trace_id = uuid.uuid4().hex
        span_id = uuid.uuid4().hex
        started_at = time.monotonic()

        try:
            response = await self._client.aio.models.generate_content(
                model=request.model,
                contents=_to_contents(request.messages),
                config=types.GenerateContentConfig(
                    system_instruction=request.system_instruction,
                    max_output_tokens=request.max_output_tokens,
                    response_mime_type="application/json" if request.response_schema else None,
                    response_schema=request.response_schema,
                    tools=request.tools,
                ),
            )
        except Exception as exc:
            self._trace_sink.write(
                TraceSpan(
                    trace_id=trace_id,
                    span_id=span_id,
                    ts=datetime.now(UTC),
                    kind="llm",
                    name="complete",
                    model=request.model,
                    prompt_id=request.prompt_id,
                    prompt_version=request.prompt_version,
                    latency_ms=int((time.monotonic() - started_at) * 1000),
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            raise

        latency_ms = int((time.monotonic() - started_at) * 1000)
        finish_reason = response.candidates[0].finish_reason.value
        incomplete = finish_reason != types.FinishReason.STOP.value

        parsed: BaseModel | None = None
        if request.response_schema is not None:
            parsed = response.parsed
            if parsed is None:
                try:
                    parsed = request.response_schema.model_validate_json(response.text)
                except Exception as exc:
                    raise ResponseValidationError(str(exc), raw_response=response.text) from exc

        usage_metadata = response.usage_metadata
        usage = TokenUsage(
            input_tokens=usage_metadata.prompt_token_count or 0,
            output_tokens=usage_metadata.candidates_token_count or 0,
        )
        cost_usd = price.cost_usd(usage.input_tokens, usage.output_tokens)
        self.total_cost_usd += cost_usd

        tool_calls = [
            part.function_call.name
            for content in (response.automatic_function_calling_history or [])
            for part in (content.parts or [])
            if part.function_call is not None
        ]

        self._trace_sink.write(
            TraceSpan(
                trace_id=trace_id,
                span_id=span_id,
                ts=datetime.now(UTC),
                kind="llm",
                name="complete",
                model=request.model,
                prompt_id=request.prompt_id,
                prompt_version=request.prompt_version,
                usage=usage.model_dump(),
                cost_usd=cost_usd,
                latency_ms=latency_ms,
            )
        )

        return LlmResult(
            text=response.text,
            parsed=parsed,
            finish_reason=finish_reason,
            incomplete=incomplete,
            usage=usage,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            trace_id=trace_id,
            span_id=span_id,
            tool_calls=tool_calls,
        )
