from pathlib import Path

from fin_ai_lab.core.llm.fake import FakeEmbeddingClient
from fin_ai_lab.filings_rag.index.embeddings import embed_with_cache


async def test_embed_with_cache_calls_the_client_for_uncached_texts(tmp_path: Path) -> None:
    client = FakeEmbeddingClient(dim=4)

    vectors = await embed_with_cache(
        ["apples", "oranges"],
        model="gemini-embedding-2",
        embedding_client=client,
        cache_dir=tmp_path,
    )

    assert len(vectors) == 2
    assert client.calls == [["apples", "oranges"]]


async def test_embed_with_cache_skips_the_client_on_a_second_call(tmp_path: Path) -> None:
    client = FakeEmbeddingClient(dim=4)

    first = await embed_with_cache(
        ["apples"], model="gemini-embedding-2", embedding_client=client, cache_dir=tmp_path
    )
    second = await embed_with_cache(
        ["apples"], model="gemini-embedding-2", embedding_client=client, cache_dir=tmp_path
    )

    assert first == second
    assert client.calls == [["apples"]]  # only the first call actually hit the client


async def test_embed_with_cache_only_fetches_the_missing_texts(tmp_path: Path) -> None:
    client = FakeEmbeddingClient(dim=4)
    await embed_with_cache(
        ["apples"], model="gemini-embedding-2", embedding_client=client, cache_dir=tmp_path
    )

    vectors = await embed_with_cache(
        ["apples", "oranges"],
        model="gemini-embedding-2",
        embedding_client=client,
        cache_dir=tmp_path,
    )

    assert len(vectors) == 2
    assert client.calls == [["apples"], ["oranges"]]


async def test_embed_with_cache_keys_by_model_too(tmp_path: Path) -> None:
    client = FakeEmbeddingClient(dim=4)
    await embed_with_cache(
        ["apples"], model="model-a", embedding_client=client, cache_dir=tmp_path
    )

    await embed_with_cache(["apples"], model="model-b", embedding_client=client, cache_dir=tmp_path)

    assert client.calls == [["apples"], ["apples"]]  # both models actually hit the client
