import pytest

from fin_ai_lab.filings_rag.index.store import VectorStore
from fin_ai_lab.filings_rag.models import Chunk


def _chunk(company: str, chunk_id: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        company=company,
        filing_type="10-K",
        fiscal_period="FY2025",
        section="ITEM 1A. RISK FACTORS",
        text="Some risk factor text.",
        source_location="https://example.test/filing.htm",
        language="en",
    )


def test_search_returns_empty_list_for_an_empty_store() -> None:
    store = VectorStore()

    assert store.search([1.0, 0.0], top_k=5) == []


def test_search_ranks_the_closest_vector_first() -> None:
    store = VectorStore()
    store.add(
        [_chunk("A", "a"), _chunk("B", "b")],
        [[1.0, 0.0], [0.0, 1.0]],
    )

    results = store.search([0.9, 0.1], top_k=2)

    assert [chunk.company for chunk, _score in results] == ["A", "B"]
    assert results[0][1] > results[1][1]


def test_search_respects_top_k() -> None:
    store = VectorStore()
    store.add(
        [_chunk("A", "a"), _chunk("B", "b"), _chunk("C", "c")],
        [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]],
    )

    results = store.search([1.0, 0.0], top_k=2)

    assert len(results) == 2


def test_add_accumulates_across_multiple_calls() -> None:
    store = VectorStore()
    store.add([_chunk("A", "a")], [[1.0, 0.0]])
    store.add([_chunk("B", "b")], [[0.0, 1.0]])

    assert len(store) == 2


def test_has_company_reflects_indexed_chunks() -> None:
    store = VectorStore()
    store.add([_chunk("Microsoft", "m")], [[1.0, 0.0]])

    assert store.has_company("Microsoft") is True
    assert store.has_company("Amazon") is False


def test_add_rejects_mismatched_lengths() -> None:
    store = VectorStore()

    with pytest.raises(ValueError, match="same length"):
        store.add([_chunk("A", "a")], [[1.0, 0.0], [0.0, 1.0]])
