from pydantic import BaseModel

from fin_ai_lab.core.llm.client import LlmRequest
from fin_ai_lab.core.llm.fake import FakeLlmClient


class Greeting(BaseModel):
    text: str


async def test_fake_client_returns_configured_response() -> None:
    client = FakeLlmClient(responses={"greet": "hello"})
    request = LlmRequest(model="gemini-2.5-flash", messages=[], prompt_id="greet")

    result = await client.complete(request)

    assert result.text == "hello"
    assert result.finish_reason == "STOP"
    assert not result.incomplete
    assert client.requests == [request]


async def test_fake_client_parses_response_schema() -> None:
    client = FakeLlmClient(responses={"greet": '{"text": "hi"}'})
    request = LlmRequest(
        model="gemini-2.5-flash",
        messages=[],
        prompt_id="greet",
        response_schema=Greeting,
    )

    result = await client.complete(request)

    assert result.parsed == Greeting(text="hi")
