import inspect
import json
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from groq import AsyncGroq
from pydantic import BaseModel

from fin_ai_lab.core.errors import ResponseValidationError, UnknownModelError
from fin_ai_lab.core.llm.client import LlmRequest, LlmResult, TokenUsage
from fin_ai_lab.core.llm.pricing import PRICES
from fin_ai_lab.core.llm.trace import TraceSink, TraceSpan

# Groq's OpenAI-compatible API has no automatic function calling (AFC) like
# google-genai's SDK — no evidence in console.groq.com/docs of a client-side
# loop for plain function tools (only for server-orchestrated built-in tools
# on specific models, not for arbitrary Python callables). GroqLlmClient
# therefore runs the tool-call loop itself. MAX_TOOL_ITERATIONS is the
# fail-safe against a model that keeps requesting tools forever — without
# it, "when does the loop stop" would depend entirely on the model
# cooperating (ADR 0007).
MAX_TOOL_ITERATIONS = 8

_JSON_TYPE_BY_ANNOTATION: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _tool_schema(tool: Callable) -> dict:
    signature = inspect.signature(tool)
    properties: dict[str, dict] = {}
    required: list[str] = []
    for name, param in signature.parameters.items():
        properties[name] = {"type": _JSON_TYPE_BY_ANNOTATION.get(param.annotation, "string")}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "type": "function",
        "function": {
            "name": tool.__name__,
            "description": inspect.getdoc(tool) or "",
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def _to_openai_messages(request: LlmRequest) -> list[dict]:
    messages: list[dict] = []
    if request.system_instruction:
        messages.append({"role": "system", "content": request.system_instruction})
    messages.extend({"role": m["role"], "content": m["text"]} for m in request.messages)
    return messages


class GroqLlmClient:
    """Second LlmClient implementation (ADR 0007), same LlmClient protocol
    as GeminiLlmClient — an independent free-tier quota for when Gemini's
    RPD is exhausted, not a replacement for it."""

    def __init__(
        self,
        api_key: str,
        trace_sink: TraceSink | None = None,
        *,
        groq_client: AsyncGroq | None = None,
    ) -> None:
        # groq_client is an injection seam for tests (no fake HTTP layer
        # exists for Groq's SDK, unlike FakeLlmClient standing in for the
        # whole LlmClient protocol elsewhere) — production code always uses
        # the default.
        self._client = groq_client or AsyncGroq(api_key=api_key)
        self._trace_sink = trace_sink or TraceSink()
        self.total_cost_usd = Decimal(0)

    async def complete(self, request: LlmRequest) -> LlmResult:
        price = PRICES.get(request.model)
        if price is None:
            raise UnknownModelError(request.model)

        trace_id = uuid.uuid4().hex
        span_id = uuid.uuid4().hex
        started_at = time.monotonic()

        messages = _to_openai_messages(request)
        tools_by_name = {tool.__name__: tool for tool in (request.tools or [])}
        tool_schemas = [_tool_schema(tool) for tool in (request.tools or [])] or None

        input_tokens = 0
        output_tokens = 0
        tool_calls: list[str] = []
        message: Any = None
        finish_reason = "max_tool_iterations"

        try:
            for _ in range(MAX_TOOL_ITERATIONS):
                response = await self._client.chat.completions.create(
                    model=request.model,
                    messages=messages,
                    max_tokens=request.max_output_tokens,
                    tools=tool_schemas,
                    response_format=(
                        {"type": "json_object"} if request.response_schema else None
                    ),
                )
                usage = response.usage
                input_tokens += usage.prompt_tokens or 0
                output_tokens += usage.completion_tokens or 0

                choice = response.choices[0]
                message = choice.message

                if not message.tool_calls:
                    finish_reason = choice.finish_reason
                    break

                messages.append(message.model_dump(exclude_none=True))
                for call in message.tool_calls:
                    tool = tools_by_name.get(call.function.name)
                    arguments = json.loads(call.function.arguments or "{}")
                    result = (
                        await tool(**arguments)
                        if tool is not None
                        else f"Unknown tool: {call.function.name}"
                    )
                    tool_calls.append(call.function.name)
                    messages.append(
                        {"role": "tool", "tool_call_id": call.id, "content": str(result)}
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
        text = (message.content if message is not None else None) or ""
        incomplete = finish_reason != "stop"

        parsed: BaseModel | None = None
        if request.response_schema is not None:
            try:
                parsed = request.response_schema.model_validate_json(text)
            except Exception as exc:
                raise ResponseValidationError(str(exc), raw_response=text) from exc

        usage_result = TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens)
        cost_usd = price.cost_usd(usage_result.input_tokens, usage_result.output_tokens)
        self.total_cost_usd += cost_usd

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
                usage=usage_result.model_dump(),
                cost_usd=cost_usd,
                latency_ms=latency_ms,
            )
        )

        return LlmResult(
            text=text,
            parsed=parsed,
            finish_reason=finish_reason,
            incomplete=incomplete,
            usage=usage_result,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            trace_id=trace_id,
            span_id=span_id,
            tool_calls=tool_calls,
        )
