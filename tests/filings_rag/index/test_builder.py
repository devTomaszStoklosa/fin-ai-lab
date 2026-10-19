import json
from pathlib import Path

import pytest
from google.genai import errors as genai_errors

from fin_ai_lab.core.llm.client import LlmRequest, LlmResult
from fin_ai_lab.core.llm.fake import FakeEmbeddingClient, FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag.corpus import ChunkLoader
from fin_ai_lab.filings_rag.index.builder import IndexBuildResult, build_index
from fin_ai_lab.filings_rag.models import Chunk

PROMPTS_DIR = Path("src/fin_ai_lab/filings_rag/prompts")
MODEL = "gemini-3.6-flash"
EMBEDDING_MODEL = "gemini-embedding-2"


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


def _chunk(company: str, chunk_id: str, text: str) -> Chunk:
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


def _loader(chunks: list[Chunk]) -> ChunkLoader:
    async def load() -> list[Chunk]:
        return chunks

    return load


def _failing_loader(exc: Exception) -> ChunkLoader:
    async def load() -> list[Chunk]:
        raise exc

    return load


def _contexts_response(chunk_ids: list[str]) -> str:
    return json.dumps(
        {
            "contexts": [
                {"chunk_id": chunk_id, "context": f"Context of {chunk_id}."}
                for chunk_id in chunk_ids
            ]
        }
    )


async def _build(
    loaders: dict[str, ChunkLoader],
    tmp_path: Path,
    llm_client: object,
    embedding_client: FakeEmbeddingClient | None = None,
) -> IndexBuildResult:
    return await build_index(
        loaders,
        llm_client=llm_client,
        prompt_registry=_prompt_registry(),
        model=MODEL,
        embedding_client=embedding_client or FakeEmbeddingClient(dim=4),
        embedding_model=EMBEDDING_MODEL,
        contextual_cache_dir=tmp_path / "contextual",
        embedding_cache_dir=tmp_path / "embeddings",
    )


async def test_build_index_adds_every_company_and_reports_its_chunk_count(tmp_path: Path) -> None:
    llm_client = FakeLlmClient({"contextual": _contexts_response(["m1", "m2", "o1"])})
    loaders = {
        "Microsoft": _loader(
            [_chunk("Microsoft", "m1", "AI risk."), _chunk("Microsoft", "m2", "Cloud.")]
        ),
        "Oracle": _loader([_chunk("Oracle", "o1", "Data centers.")]),
    }

    result = await _build(loaders, tmp_path, llm_client)

    assert [chunk.id for chunk in result.store.chunks] == ["m1", "m2", "o1"]
    assert [(s.company, s.chunk_count, s.skipped_reason) for s in result.statuses] == [
        ("Microsoft", 2, None),
        ("Oracle", 1, None),
    ]


async def test_build_index_embeds_the_context_with_the_chunk_but_keeps_the_raw_text(
    tmp_path: Path,
) -> None:
    llm_client = FakeLlmClient({"contextual": _contexts_response(["m1"])})
    embedding_client = FakeEmbeddingClient(dim=4)

    result = await _build(
        {"Microsoft": _loader([_chunk("Microsoft", "m1", "AI risk.")])},
        tmp_path,
        llm_client,
        embedding_client,
    )

    assert embedding_client.calls == [["Context of m1.\n\nAI risk."]]
    assert result.store.chunks[0].text == "AI risk."


async def test_build_index_skips_a_company_whose_source_cannot_be_read(tmp_path: Path) -> None:
    llm_client = FakeLlmClient({"contextual": _contexts_response(["o1"])})
    loaders = {
        "Atrem": _failing_loader(FileNotFoundError("Atrem.pdf")),
        "Oracle": _loader([_chunk("Oracle", "o1", "Data centers.")]),
    }

    result = await _build(loaders, tmp_path, llm_client)

    assert [chunk.company for chunk in result.store.chunks] == ["Oracle"]
    assert result.statuses[0].company == "Atrem"
    assert result.statuses[0].skipped_reason == "FileNotFoundError: Atrem.pdf"


async def test_build_index_skips_a_company_with_no_chunks(tmp_path: Path) -> None:
    result = await _build({"Citigroup": _loader([])}, tmp_path, FakeLlmClient({}))

    assert len(result.store) == 0
    assert result.statuses[0].skipped_reason == "no chunks found"


class _QuotaExhaustedForCompany:
    """Fails the contextualize call for one company only — like hitting
    Gemini's daily cap partway through a build."""

    def __init__(self, inner: FakeLlmClient, failing_company: str) -> None:
        self._inner = inner
        self._failing_company = failing_company

    async def complete(self, request: LlmRequest) -> LlmResult:
        if self._failing_company in request.messages[0]["text"]:
            raise genai_errors.ClientError(
                429, {"error": {"message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}}
            )
        return await self._inner.complete(request)


async def test_build_index_skips_a_company_when_gemini_fails_and_keeps_the_rest(
    tmp_path: Path,
) -> None:
    inner = FakeLlmClient({"contextual": _contexts_response(["m1"])})
    llm_client = _QuotaExhaustedForCompany(inner, failing_company="Oracle")
    loaders = {
        "Oracle": _loader([_chunk("Oracle", "o1", "Data centers.")]),
        "Microsoft": _loader([_chunk("Microsoft", "m1", "AI risk.")]),
    }

    result = await _build(loaders, tmp_path, llm_client)

    assert [chunk.company for chunk in result.store.chunks] == ["Microsoft"]
    assert result.statuses[0].company == "Oracle"
    assert result.statuses[0].skipped_reason.startswith("ClientError: 429")


async def test_build_index_reuses_cached_work_on_a_second_run(tmp_path: Path) -> None:
    loaders = {"Microsoft": _loader([_chunk("Microsoft", "m1", "AI risk.")])}
    first_llm = FakeLlmClient({"contextual": _contexts_response(["m1"])})
    await _build(loaders, tmp_path, first_llm)

    second_llm = FakeLlmClient({})
    second_embeddings = FakeEmbeddingClient(dim=4)
    result = await _build(loaders, tmp_path, second_llm, second_embeddings)

    assert len(result.store) == 1
    assert second_llm.requests == []
    assert second_embeddings.calls == []


async def test_build_index_does_not_swallow_unexpected_errors(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        await _build(
            {"Microsoft": _failing_loader(RuntimeError("bug"))}, tmp_path, FakeLlmClient({})
        )
