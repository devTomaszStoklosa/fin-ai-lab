import json
from pathlib import Path

import pytest
from google.genai import errors as genai_errors

from fin_ai_lab.core.llm.fake import FakeEmbeddingClient, FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag import qa_target
from fin_ai_lab.filings_rag.corpus import ChunkLoader
from fin_ai_lab.filings_rag.index.store import VectorStore
from fin_ai_lab.filings_rag.models import Chunk
from fin_ai_lab.filings_rag.qa_target import (
    EvalIndexIncompleteError,
    _available_loaders,
    _build_eval_store,
    _get_store,
)

PROMPTS_DIR = Path("src/fin_ai_lab/filings_rag/prompts")
MODEL = "gemini-3.6-flash"


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


def _chunk(company: str, chunk_id: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        company=company,
        filing_type="10-K",
        fiscal_period="FY2026",
        section="ITEM 1A. RISK FACTORS",
        text=f"Risk text of {company}.",
        source_location="https://example.test/filing.htm",
        language="en",
    )


def _loader(chunks: list[Chunk]) -> ChunkLoader:
    async def load() -> list[Chunk]:
        return chunks

    return load


def _failing_loader(exc: Exception) -> ChunkLoader:
    async def load() -> list[Chunk]:
        raise exc

    return load


def _contexts(chunk_ids: list[str]) -> str:
    return json.dumps(
        {"contexts": [{"chunk_id": chunk_id, "context": "Context."} for chunk_id in chunk_ids]}
    )


async def _build(loaders: dict[str, ChunkLoader], tmp_path: Path, llm_client) -> VectorStore:
    return await _build_eval_store(
        loaders,
        llm_client=llm_client,
        prompt_registry=_prompt_registry(),
        model=MODEL,
        embedding_client=FakeEmbeddingClient(dim=4),
        contextual_cache_dir=tmp_path / "contextual",
        embedding_cache_dir=tmp_path / "embeddings",
    )


def test_available_loaders_leaves_out_gpw_companies_whose_pdf_is_missing(tmp_path: Path) -> None:
    present = tmp_path / "present.pdf"
    present.write_bytes(b"%PDF")
    loaders = {
        "Microsoft": _loader([]),
        "Atrem": _loader([]),
        "PKN Orlen": _loader([]),
    }

    available = _available_loaders(
        loaders, {"Atrem": present, "PKN Orlen": tmp_path / "missing.pdf"}
    )

    assert list(available) == ["Microsoft", "Atrem"]


async def test_build_eval_store_indexes_every_company(tmp_path: Path) -> None:
    llm_client = FakeLlmClient({"contextual": _contexts(["m1", "o1"])})
    loaders = {
        "Microsoft": _loader([_chunk("Microsoft", "m1")]),
        "Oracle": _loader([_chunk("Oracle", "o1")]),
    }

    store = await _build(loaders, tmp_path, llm_client)

    assert [chunk.id for chunk in store.chunks] == ["m1", "o1"]


async def test_build_eval_store_accepts_a_company_with_no_chunks(tmp_path: Path) -> None:
    llm_client = FakeLlmClient({"contextual": _contexts(["m1"])})
    loaders = {
        "Microsoft": _loader([_chunk("Microsoft", "m1")]),
        "Citigroup": _loader([]),
    }

    store = await _build(loaders, tmp_path, llm_client)

    assert [chunk.company for chunk in store.chunks] == ["Microsoft"]


async def test_build_eval_store_stops_instead_of_using_a_partial_index(tmp_path: Path) -> None:
    llm_client = FakeLlmClient({"contextual": _contexts(["m1"])})
    loaders = {
        "Microsoft": _loader([_chunk("Microsoft", "m1")]),
        "Amazon": _failing_loader(
            genai_errors.ServerError(
                503, {"error": {"message": "High demand", "status": "UNAVAILABLE"}}
            )
        ),
    }

    with pytest.raises(EvalIndexIncompleteError) as excinfo:
        await _build(loaders, tmp_path, llm_client)

    assert [status.company for status in excinfo.value.failures] == ["Amazon"]
    assert "Amazon: ServerError: 503" in str(excinfo.value)


async def test_get_store_builds_once_and_does_not_keep_a_failed_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = VectorStore()
    calls: list[int] = []

    async def fake_build_eval_store(loaders, **kwargs) -> VectorStore:
        calls.append(1)
        if len(calls) == 1:
            raise EvalIndexIncompleteError([])
        return built

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("SEC_USER_AGENT", "test agent test@example.test")
    monkeypatch.setattr(qa_target, "_store", None)
    monkeypatch.setattr(qa_target, "_build_eval_store", fake_build_eval_store)

    with pytest.raises(EvalIndexIncompleteError):
        await _get_store(FakeLlmClient({}), _prompt_registry(), MODEL)
    first = await _get_store(FakeLlmClient({}), _prompt_registry(), MODEL)
    second = await _get_store(FakeLlmClient({}), _prompt_registry(), MODEL)

    assert first is built
    assert second is built
    assert len(calls) == 2
