from decimal import Decimal

from pydantic import BaseModel

from fin_ai_lab.core.llm.client import LlmRequest
from fin_ai_lab.core.llm.fake import FakeEmbeddingClient, FakeLlmClient


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


async def test_fake_embedding_client_returns_a_distinct_vector_per_text() -> None:
    client = FakeEmbeddingClient(dim=4)

    result = await client.embed(["apples", "oranges"], model="gemini-embedding-2")

    assert len(result.vectors) == 2
    assert result.vectors[0] != result.vectors[1]
    assert all(len(v) == 4 for v in result.vectors)
    assert result.cost_usd == Decimal(0)
    assert client.calls == [["apples", "oranges"]]


async def test_fake_embedding_client_is_deterministic_for_the_same_text() -> None:
    client = FakeEmbeddingClient(dim=4)

    first = await client.embed(["apples"], model="gemini-embedding-2")
    second = await client.embed(["apples"], model="gemini-embedding-2")

    assert first.vectors == second.vectors
