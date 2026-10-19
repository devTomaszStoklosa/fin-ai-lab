from fin_ai_lab.core.llm.fake import FakeEmbeddingClient
from fin_ai_lab.filings_rag.index.store import VectorStore
from fin_ai_lab.filings_rag.models import Chunk
from fin_ai_lab.filings_rag.retrieval.hybrid import retrieve_hybrid


def _chunk(company: str, text: str, *, fiscal_period: str = "FY2025") -> Chunk:
    return Chunk(
        id=f"{company}:{fiscal_period}:{text[:8]}",
        company=company,
        filing_type="10-K",
        fiscal_period=fiscal_period,
        section="ITEM 1A. RISK FACTORS",
        text=text,
        source_location="https://example.test/filing.htm",
        language="en",
    )


async def _store_with(client: FakeEmbeddingClient, chunks: list[Chunk]) -> VectorStore:
    store = VectorStore()
    embedded = await client.embed([chunk.text for chunk in chunks], model="fake-model")
    store.add(chunks, embedded.vectors)
    return store


async def test_retrieve_hybrid_ranks_the_exact_keyword_match_first() -> None:
    # FakeEmbeddingClient's vectors are unrelated to meaning, so any signal
    # here comes from BM25 (weighted higher for financial data per
    # 03-design.md P2-S3) — the chunk naming "supply chain shortage" should
    # outrank an unrelated chunk regardless of what the fake embedding says.
    client = FakeEmbeddingClient(dim=4)
    chunks = [
        _chunk("Oracle", "supply chain shortage risk for cloud hardware"),
        _chunk("Oracle", "unrelated commentary about office culture"),
    ]
    store = await _store_with(client, chunks)

    result = await retrieve_hybrid(
        "supply chain shortage",
        store,
        embedding_client=client,
        embedding_model="fake-model",
    )

    assert result.chunks[0].chunk.text.startswith("supply chain shortage")


async def test_retrieve_hybrid_filters_by_company() -> None:
    client = FakeEmbeddingClient(dim=4)
    chunks = [
        _chunk("Oracle", "cloud strategy risk"),
        _chunk("Amazon", "cloud strategy risk"),
    ]
    store = await _store_with(client, chunks)

    result = await retrieve_hybrid(
        "cloud strategy risk",
        store,
        embedding_client=client,
        embedding_model="fake-model",
        company="Amazon",
    )

    assert all(retrieved.chunk.company == "Amazon" for retrieved in result.chunks)


async def test_retrieve_hybrid_filters_by_fiscal_period() -> None:
    client = FakeEmbeddingClient(dim=4)
    chunks = [
        _chunk("Oracle", "cloud strategy risk", fiscal_period="FY2024"),
        _chunk("Oracle", "cloud strategy risk", fiscal_period="FY2025"),
    ]
    store = await _store_with(client, chunks)

    result = await retrieve_hybrid(
        "cloud strategy risk",
        store,
        embedding_client=client,
        embedding_model="fake-model",
        fiscal_period="FY2025",
    )

    assert all(retrieved.chunk.fiscal_period == "FY2025" for retrieved in result.chunks)


async def test_retrieve_hybrid_flags_company_not_in_corpus() -> None:
    client = FakeEmbeddingClient(dim=4)
    store = await _store_with(client, [_chunk("Oracle", "cloud strategy risk")])

    result = await retrieve_hybrid(
        "What are Nvidia's risks?",
        store,
        embedding_client=client,
        embedding_model="fake-model",
        known_companies=["Oracle", "Amazon"],
    )

    assert result.company_in_corpus is False


async def test_retrieve_hybrid_returns_zero_top_score_for_an_empty_store() -> None:
    client = FakeEmbeddingClient(dim=4)
    store = VectorStore()

    result = await retrieve_hybrid(
        "anything", store, embedding_client=client, embedding_model="fake-model"
    )

    assert result.chunks == []
    assert result.top_score == 0.0
