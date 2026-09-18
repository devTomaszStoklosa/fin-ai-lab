from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from fin_ai_lab.core.errors import ResponseValidationError, UnknownModelError
from fin_ai_lab.core.llm.client import LlmRequest
from fin_ai_lab.core.llm.groq_client import MAX_TOOL_ITERATIONS, GroqLlmClient


class Greeting(BaseModel):
    text: str


class _FakeMessage:
    def __init__(self, content, tool_calls=None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []

    def model_dump(self, exclude_none: bool = True) -> dict:
        dump: dict = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            dump["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ]
        return dump


class _FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.function = SimpleNamespace(name=name, arguments=arguments)


class _FakeResponse:
    def __init__(
        self,
        content: str | None,
        *,
        finish_reason: str = "stop",
        tool_calls: list[_FakeToolCall] | None = None,
        prompt_tokens: int = 10,
        completion_tokens: int = 5,
    ) -> None:
        self.choices = [
            SimpleNamespace(
                message=_FakeMessage(content, tool_calls), finish_reason=finish_reason
            )
        ]
        self.usage = SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )


class _FakeGroqClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


async def test_complete_raises_for_unknown_model() -> None:
    client = GroqLlmClient("key", groq_client=_FakeGroqClient([]))
    request = LlmRequest(model="not-a-real-model", messages=[{"role": "user", "text": "hi"}])

    with pytest.raises(UnknownModelError):
        await client.complete(request)


async def test_complete_returns_text_and_cost_without_tools() -> None:
    fake = _FakeGroqClient([_FakeResponse("pong")])
    client = GroqLlmClient("key", groq_client=fake)
    request = LlmRequest(model="openai/gpt-oss-20b", messages=[{"role": "user", "text": "ping"}])

    result = await client.complete(request)

    assert result.text == "pong"
    assert result.finish_reason == "stop"
    assert not result.incomplete
    assert result.cost_usd > Decimal(0)
    assert result.tool_calls == []
    assert client.total_cost_usd == result.cost_usd


async def test_complete_executes_tools_until_final_answer() -> None:
    calls_made = []

    async def get_price() -> str:
        calls_made.append("get_price")
        return "100 PLN"

    tool_call = _FakeToolCall("call-1", "get_price", "{}")
    fake = _FakeGroqClient(
        [
            _FakeResponse(None, finish_reason="tool_calls", tool_calls=[tool_call]),
            _FakeResponse("Price is 100 PLN"),
        ]
    )
    client = GroqLlmClient("key", groq_client=fake)
    request = LlmRequest(
        model="openai/gpt-oss-20b",
        messages=[{"role": "user", "text": "what's the price?"}],
        tools=[get_price],
    )

    result = await client.complete(request)

    assert result.text == "Price is 100 PLN"
    assert result.tool_calls == ["get_price"]
    assert calls_made == ["get_price"]
    assert len(fake.calls) == 2


async def test_complete_stops_after_max_iterations_when_model_keeps_calling_tools() -> None:
    async def noop() -> str:
        return "x"

    responses = [
        _FakeResponse(
            None, finish_reason="tool_calls", tool_calls=[_FakeToolCall("call-1", "noop", "{}")]
        )
        for _ in range(MAX_TOOL_ITERATIONS)
    ]
    fake = _FakeGroqClient(responses)
    client = GroqLlmClient("key", groq_client=fake)
    request = LlmRequest(
        model="openai/gpt-oss-20b", messages=[{"role": "user", "text": "loop"}], tools=[noop]
    )

    result = await client.complete(request)

    assert result.incomplete
    assert result.finish_reason == "max_tool_iterations"
    assert len(fake.calls) == MAX_TOOL_ITERATIONS


async def test_complete_raises_response_validation_error_on_schema_mismatch() -> None:
    fake = _FakeGroqClient([_FakeResponse("not json")])
    client = GroqLlmClient("key", groq_client=fake)
    request = LlmRequest(
        model="openai/gpt-oss-20b",
        messages=[{"role": "user", "text": "hi"}],
        response_schema=Greeting,
    )

    with pytest.raises(ResponseValidationError):
        await client.complete(request)
