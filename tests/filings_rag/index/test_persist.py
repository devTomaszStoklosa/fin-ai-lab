from datetime import UTC, datetime
from pathlib import Path

import pytest

from fin_ai_lab.filings_rag.index.persist import load_index, save_index
from fin_ai_lab.filings_rag.index.store import VectorStore
from fin_ai_lab.filings_rag.models import Chunk

BUILT_AT = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)


def _chunk(company: str, chunk_id: str, text: str = "Some risk factor text.") -> Chunk:
    return Chunk(
        id=chunk_id,
        company=company,
        filing_type="10-K",
        fiscal_period="FY2025",
        section="ITEM 1A. RISK FACTORS",
        text=text,
        source_location="https://example.test/filing.htm",
        language="en",
    )


def _store() -> VectorStore:
    store = VectorStore()
    store.add(
        [_chunk("Microsoft", "a", "Ryzyko związane z AI."), _chunk("Oracle", "b")],
        [[1.0, 0.0, 0.5], [0.0, 1.0, 0.25]],
    )
    return store


def test_load_index_returns_none_when_nothing_was_saved(tmp_path: Path) -> None:
    assert load_index(tmp_path / "index.npz") is None


def test_saved_index_loads_back_with_the_same_chunks_and_metadata(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "index.npz"
    store = _store()

    save_index(store, embedding_model="gemini-embedding-2", built_at=BUILT_AT, path=path)
    loaded = load_index(path)

    assert loaded is not None
    assert loaded.store.chunks == store.chunks
    assert loaded.embedding_model == "gemini-embedding-2"
    assert loaded.built_at == BUILT_AT


def test_saved_index_ranks_search_results_the_same_as_the_original(tmp_path: Path) -> None:
    path = tmp_path / "index.npz"
    store = _store()

    save_index(store, embedding_model="gemini-embedding-2", built_at=BUILT_AT, path=path)
    loaded = load_index(path)

    assert loaded is not None
    query = [0.9, 0.1, 0.4]
    original = [(chunk.id, round(score, 5)) for chunk, score in store.search(query, top_k=2)]
    reloaded = [(chunk.id, round(score, 5)) for chunk, score in loaded.store.search(query, top_k=2)]
    assert reloaded == original


def test_save_index_replaces_an_earlier_index_without_leaving_a_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "index.npz"
    save_index(_store(), embedding_model="gemini-embedding-2", built_at=BUILT_AT, path=path)

    smaller = VectorStore()
    smaller.add([_chunk("Amazon", "c")], [[0.5, 0.5, 0.5]])
    save_index(smaller, embedding_model="gemini-embedding-2", built_at=BUILT_AT, path=path)

    loaded = load_index(path)
    assert loaded is not None
    assert [chunk.company for chunk in loaded.store.chunks] == ["Amazon"]
    assert [p.name for p in tmp_path.iterdir()] == ["index.npz"]


def test_save_index_refuses_an_empty_store(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_index(
            VectorStore(),
            embedding_model="gemini-embedding-2",
            built_at=BUILT_AT,
            path=tmp_path / "index.npz",
        )

    assert not (tmp_path / "index.npz").exists()
