from fin_ai_lab.core.llm.fake import FakeEmbeddingClient
from fin_ai_lab.filings_rag.index.store import VectorStore
from fin_ai_lab.filings_rag.models import Chunk
from fin_ai_lab.filings_rag.retrieval.naive import retrieve


def _chunk(company: str, text: str) -> Chunk:
    return Chunk(
        id=f"{company}:{text[:8]}",
        company=company,
        filing_type="10-K",
        fiscal_period="FY2025",
        section="ITEM 1A. RISK FACTORS",
        text=text,
        source_location="https://example.test/filing.htm",
        language="en",
    )


async def test_retrieve_returns_chunks_ranked_by_similarity() -> None:
    client = FakeEmbeddingClient(dim=4)
    store = VectorStore()
    chunks = [_chunk("Microsoft", "risk factor about competition")]
    # Build the store from the same fake embeddings the query will use, so
    # similarity is meaningful for this test.
    embedded = await client.embed([c.text for c in chunks], model="fake-model")
    store.add(chunks, embedded.vectors)

    result = await retrieve(
        "risk factor about competition",
        store,
        embedding_client=client,
        embedding_model="fake-model",
    )

    assert len(result.chunks) == 1
    assert result.chunks[0].chunk.company == "Microsoft"
    assert result.top_score == result.chunks[0].score


async def test_retrieve_flags_company_not_in_corpus() -> None:
    client = FakeEmbeddingClient(dim=4)
    store = VectorStore()
    chunk = _chunk("Microsoft", "risk factor text")
    embedded = await client.embed([chunk.text], model="fake-model")
    store.add([chunk], embedded.vectors)

    result = await retrieve(
        "What are Nvidia's risks?",
        store,
        embedding_client=client,
        embedding_model="fake-model",
        known_companies=["Microsoft", "Amazon"],
    )

    assert result.company_in_corpus is False


async def test_retrieve_recognizes_a_known_company_case_insensitively() -> None:
    client = FakeEmbeddingClient(dim=4)
    store = VectorStore()
    chunk = _chunk("Microsoft", "risk factor text")
    embedded = await client.embed([chunk.text], model="fake-model")
    store.add([chunk], embedded.vectors)

    result = await retrieve(
        "What are microsoft's risks?",
        store,
        embedding_client=client,
        embedding_model="fake-model",
        known_companies=["Microsoft", "Amazon"],
    )

    assert result.company_in_corpus is True


async def test_retrieve_returns_zero_top_score_for_an_empty_store() -> None:
    client = FakeEmbeddingClient(dim=4)
    store = VectorStore()

    result = await retrieve(
        "anything", store, embedding_client=client, embedding_model="fake-model"
    )

    assert result.chunks == []
    assert result.top_score == 0.0
