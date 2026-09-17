from pathlib import Path

from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag.models import Chunk, RetrievedChunk
from fin_ai_lab.filings_rag.retrieval.rerank import rerank

PROMPTS_DIR = Path("src/fin_ai_lab/filings_rag/prompts")
MODEL = "gemini-3.6-flash"


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


def _candidate(chunk_id: str, score: float) -> RetrievedChunk:
    chunk = Chunk(
        id=chunk_id,
        company="Oracle",
        filing_type="10-K",
        fiscal_period="FY2025",
        section="ITEM 1A. RISK FACTORS",
        text=f"text for {chunk_id}",
        source_location="https://example.test/filing.htm",
        language="en",
    )
    return RetrievedChunk(chunk=chunk, score=score)


async def test_rerank_reorders_by_llm_relevance_score(tmp_path: Path) -> None:
    draft = (
        '{"scores": [{"chunk_id": "a", "relevance_score": 0.2}, '
        '{"chunk_id": "b", "relevance_score": 0.9}]}'
    )
    llm_client = FakeLlmClient({"rerank": draft})
    candidates = [_candidate("a", 0.8), _candidate("b", 0.3)]

    reordered = await rerank(
        "question", candidates, llm_client, _prompt_registry(), MODEL, cache_dir=tmp_path
    )

    assert [retrieved.chunk.id for retrieved in reordered] == ["b", "a"]
    assert reordered[0].score == 0.9


async def test_rerank_keeps_incoming_score_for_a_chunk_the_model_skipped(tmp_path: Path) -> None:
    draft = '{"scores": [{"chunk_id": "a", "relevance_score": 0.1}]}'
    llm_client = FakeLlmClient({"rerank": draft})
    candidates = [_candidate("a", 0.5), _candidate("b", 0.7)]

    reordered = await rerank(
        "question", candidates, llm_client, _prompt_registry(), MODEL, cache_dir=tmp_path
    )

    assert {retrieved.chunk.id for retrieved in reordered} == {"a", "b"}
    skipped = next(retrieved for retrieved in reordered if retrieved.chunk.id == "b")
    assert skipped.score == 0.7


async def test_rerank_caches_the_result_and_skips_a_second_llm_call(tmp_path: Path) -> None:
    draft = '{"scores": [{"chunk_id": "a", "relevance_score": 0.9}]}'
    llm_client = FakeLlmClient({"rerank": draft})
    candidates = [_candidate("a", 0.1)]

    await rerank("question", candidates, llm_client, _prompt_registry(), MODEL, cache_dir=tmp_path)
    await rerank("question", candidates, llm_client, _prompt_registry(), MODEL, cache_dir=tmp_path)

    assert len(llm_client.requests) == 1


async def test_rerank_returns_empty_list_without_calling_the_llm() -> None:
    llm_client = FakeLlmClient({})  # would KeyError if ever called

    reordered = await rerank("question", [], llm_client, _prompt_registry(), MODEL)

    assert reordered == []
