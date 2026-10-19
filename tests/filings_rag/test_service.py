import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fin_ai_lab.core.llm.embeddings import EmbeddingResult
from fin_ai_lab.core.llm.fake import FakeEmbeddingClient, FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag.index.persist import SavedIndex, save_index
from fin_ai_lab.filings_rag.index.store import VectorStore
from fin_ai_lab.filings_rag.models import Chunk
from fin_ai_lab.filings_rag.service import (
    PROMPTS_DIR,
    SavedIndexCache,
    UnknownCompanyError,
    ask,
    indexed_companies,
)

MODEL = "gemini-3.6-flash"
BUILT_AT = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)


class _RecordingEmbeddingClient(FakeEmbeddingClient):
    def __init__(self) -> None:
        super().__init__(dim=4)
        self.models: list[str] = []

    async def embed(self, texts: list[str], model: str) -> EmbeddingResult:
        self.models.append(model)
        return await super().embed(texts, model)


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


def _chunk(company: str, chunk_id: str, text: str, section: str = "ITEM 1A. RISK FACTORS") -> Chunk:
    return Chunk(
        id=chunk_id,
        company=company,
        filing_type="10-K",
        fiscal_period="FY2026",
        section=section,
        text=text,
        source_location="https://example.test/filing.htm",
        language="en",
    )


def _store() -> VectorStore:
    store = VectorStore()
    store.add(
        [
            _chunk("Microsoft", "m1", "Artificial intelligence may harm our reputation."),
            _chunk("Microsoft", "m2", "Datacenter capacity constraints.", section="ITEM 7. MD&A"),
            _chunk("Oracle", "o1", "Oracle Cloud artificial intelligence demand."),
            _chunk("Oracle", "o2", "Customer contract renewals."),
        ],
        [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]],
    )
    return store


def _index() -> SavedIndex:
    return SavedIndex(store=_store(), embedding_model="gemini-embedding-2", built_at=BUILT_AT)


def _answer_response(company: str, excerpt: str) -> str:
    return json.dumps(
        {
            "text": "The company describes AI-related reputational risk.",
            "citations": [
                {
                    "company": company,
                    "filing_type": "10-K",
                    "fiscal_period": "FY2026",
                    "section": "ITEM 1A. RISK FACTORS",
                    "excerpt": excerpt,
                }
            ],
        }
    )


def test_indexed_companies_lists_each_company_once_in_index_order() -> None:
    companies = indexed_companies(_index())

    assert [(c.company, c.chunk_count) for c in companies] == [("Microsoft", 2), ("Oracle", 2)]
    assert companies[0].sections == ["ITEM 1A. RISK FACTORS", "ITEM 7. MD&A"]
    assert companies[0].filing_type == "10-K"
    assert companies[0].fiscal_period == "FY2026"


async def test_ask_with_a_company_searches_only_that_company_with_one_call_each() -> None:
    llm_client = FakeLlmClient(
        {"answer": _answer_response("Oracle", "Oracle Cloud artificial intelligence demand.")}
    )
    embedding_client = _RecordingEmbeddingClient()

    answer = await ask(
        "What artificial intelligence risks are described?",
        _index(),
        company="Oracle",
        llm_client=llm_client,
        embedding_client=embedding_client,
        prompt_registry=_prompt_registry(),
        model=MODEL,
    )

    assert not answer.refused
    assert answer.citations[0].company == "Oracle"
    assert len(embedding_client.calls) == 1
    assert len(llm_client.requests) == 1
    prompt_text = llm_client.requests[0].messages[0]["text"]
    assert "Oracle Cloud" in prompt_text
    assert "Microsoft" not in prompt_text


async def test_ask_embeds_the_question_with_the_index_embedding_model() -> None:
    embedding_client = _RecordingEmbeddingClient()
    llm_client = FakeLlmClient({"answer": _answer_response("Microsoft", "may harm our reputation")})

    await ask(
        "Which artificial intelligence risks harm reputation?",
        _index(),
        company="Microsoft",
        llm_client=llm_client,
        embedding_client=embedding_client,
        prompt_registry=_prompt_registry(),
        model=MODEL,
    )

    assert embedding_client.models == ["gemini-embedding-2"]


async def test_ask_without_a_company_refuses_a_question_naming_no_indexed_company() -> None:
    llm_client = FakeLlmClient({})

    answer = await ask(
        "What risks does Nvidia disclose?",
        _index(),
        company=None,
        llm_client=llm_client,
        embedding_client=FakeEmbeddingClient(dim=4),
        prompt_registry=_prompt_registry(),
        model=MODEL,
    )

    assert answer.refused
    assert answer.refusal_reason == "company_not_in_corpus"
    assert llm_client.requests == []


async def test_ask_rejects_a_company_that_is_not_in_the_index() -> None:
    with pytest.raises(UnknownCompanyError):
        await ask(
            "What risks are described?",
            _index(),
            company="Nvidia",
            llm_client=FakeLlmClient({}),
            embedding_client=FakeEmbeddingClient(dim=4),
            prompt_registry=_prompt_registry(),
            model=MODEL,
        )


def test_saved_index_cache_returns_none_without_a_saved_index(tmp_path: Path) -> None:
    assert SavedIndexCache(tmp_path / "index.npz").get() is None


def test_saved_index_cache_reloads_only_after_the_file_changes(tmp_path: Path) -> None:
    path = tmp_path / "index.npz"
    save_index(_store(), embedding_model="gemini-embedding-2", built_at=BUILT_AT, path=path)
    cache = SavedIndexCache(path)

    first = cache.get()
    assert cache.get() is first

    smaller = VectorStore()
    smaller.add([_chunk("Amazon", "a1", "Seasonality.")], [[1.0, 0.0, 0.0, 0.0]])
    save_index(smaller, embedding_model="gemini-embedding-2", built_at=BUILT_AT, path=path)
    # Make sure the new file's modification time differs even on a coarse
    # filesystem clock.
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    reloaded = cache.get()
    assert reloaded is not first
    assert [chunk.company for chunk in reloaded.store.chunks] == ["Amazon"]

    path.unlink()
    assert cache.get() is None
