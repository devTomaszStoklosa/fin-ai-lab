import time
from decimal import Decimal
from types import SimpleNamespace

import pytest

from fin_ai_lab.core.errors import UnknownModelError
from fin_ai_lab.core.llm.embeddings import MAX_BATCH_SIZE, GeminiEmbeddingClient


def _fake_response(num_embeddings: int) -> SimpleNamespace:
    embeddings = [SimpleNamespace(values=[0.1, 0.2]) for _ in range(num_embeddings)]
    return SimpleNamespace(embeddings=embeddings)


async def test_embed_splits_into_batches_of_at_most_max_batch_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiEmbeddingClient(api_key="fake", seconds_per_item=0.0)
    calls: list[int] = []

    async def fake_embed_content(*, model: str, contents: list) -> SimpleNamespace:
        calls.append(len(contents))
        return _fake_response(len(contents))

    monkeypatch.setattr(client._client.aio.models, "embed_content", fake_embed_content)

    texts = [f"text {i}" for i in range(150)]
    result = await client.embed(texts, model="gemini-embedding-2")

    assert calls == [MAX_BATCH_SIZE] * (150 // MAX_BATCH_SIZE) + [150 % MAX_BATCH_SIZE]
    assert len(result.vectors) == 150


async def test_embed_accumulates_cost_across_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GeminiEmbeddingClient(api_key="fake", seconds_per_item=0.0)

    async def fake_embed_content(*, model: str, contents: list) -> SimpleNamespace:
        return _fake_response(len(contents))

    monkeypatch.setattr(client._client.aio.models, "embed_content", fake_embed_content)

    result = await client.embed([f"text {i}" for i in range(150)], model="gemini-embedding-2")

    assert result.cost_usd > 0
    assert client.total_cost_usd == result.cost_usd


async def test_embed_paces_the_next_call_by_the_previous_batch_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # seconds_per_item=0.05 and 2 batches of 4 items each -> the second call
    # must wait ~4 * 0.05 = 0.2s after the first, regardless of MAX_BATCH_SIZE.
    client = GeminiEmbeddingClient(api_key="fake", seconds_per_item=0.05)

    async def fake_embed_content(*, model: str, contents: list) -> SimpleNamespace:
        return _fake_response(len(contents))

    monkeypatch.setattr(client._client.aio.models, "embed_content", fake_embed_content)

    started = time.monotonic()
    await client._embed_batch(["a", "b", "c", "d"], "gemini-embedding-2")
    await client._embed_batch(["e", "f", "g", "h"], "gemini-embedding-2")
    elapsed = time.monotonic() - started

    assert elapsed >= 0.18  # small tolerance under the expected 0.2s


async def test_embed_raises_for_an_unknown_model() -> None:
    client = GeminiEmbeddingClient(api_key="fake")

    with pytest.raises(UnknownModelError):
        await client.embed(["text"], model="not-a-real-model")


async def test_embed_returns_zero_vectors_for_empty_input(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GeminiEmbeddingClient(api_key="fake")
    calls = {"n": 0}

    async def fake_embed_content(*, model: str, contents: list) -> SimpleNamespace:
        calls["n"] += 1
        return _fake_response(len(contents))

    monkeypatch.setattr(client._client.aio.models, "embed_content", fake_embed_content)

    result = await client.embed([], model="gemini-embedding-2")

    assert result.vectors == []
    assert result.cost_usd == Decimal(0)
    assert calls["n"] == 0
