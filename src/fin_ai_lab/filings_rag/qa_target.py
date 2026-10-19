import asyncio
from pathlib import Path

from fin_ai_lab.core.config import Settings
from fin_ai_lab.core.evals.models import RunContext
from fin_ai_lab.core.llm.client import LlmClient
from fin_ai_lab.core.llm.embeddings import GeminiEmbeddingClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag.answer.builder import build_answer
from fin_ai_lab.filings_rag.corpus import (
    EMBEDDING_MODEL,
    GPW_COMPANIES,
    US_COMPANIES,
    ChunkLoader,
    corpus_loaders,
)
from fin_ai_lab.filings_rag.index.builder import NO_CHUNKS_REASON, CompanyBuildStatus, build_index
from fin_ai_lab.filings_rag.index.persist import load_index
from fin_ai_lab.filings_rag.index.store import VectorStore
from fin_ai_lab.filings_rag.ingest.sec_edgar import SecEdgarClient
from fin_ai_lab.filings_rag.models import RetrievalResult
from fin_ai_lab.filings_rag.retrieval.hybrid import DEFAULT_TOP_K, retrieve_hybrid
from fin_ai_lab.filings_rag.retrieval.rerank import rerank
from fin_ai_lab.filings_rag.service import ask

# Wider recall pool for the reranker to work with than the final answer
# needs (03-design.md P2-S3) — hybrid search casts a broader net, rerank
# narrows it back down to DEFAULT_TOP_K before the refusal-threshold check.
RERANK_CANDIDATE_POOL = 15

# Built once per process and reused across every case in an eval run — the
# eval harness only tracks cost via ctx.llm_client, so building the index
# (SEC fetch + embeddings) here instead of on every case keeps that cost
# accounting meaningful: after the first real run this is a disk-cache-only
# rebuild (no network, no billed tokens), and no core.evals contract needed
# an embedding-client-aware cost path just for this one target.
_build_lock = asyncio.Lock()
_store: VectorStore | None = None


class EvalIndexIncompleteError(RuntimeError):
    """The eval's index couldn't be built for every company — the eval stops
    instead of running on a partial index, where a missing company would
    show up as a wrong answer, as if the model were at fault."""

    def __init__(self, failures: list[CompanyBuildStatus]) -> None:
        reasons = "; ".join(f"{status.company}: {status.skipped_reason}" for status in failures)
        super().__init__(f"Filings index incomplete, eval stopped: {reasons}")
        self.failures = failures


async def _get_store(
    llm_client: LlmClient, prompt_registry: PromptRegistry, model: str
) -> VectorStore:
    global _store
    async with _build_lock:
        if _store is not None:
            return _store

        settings = Settings()
        sec_client = SecEdgarClient(settings.require_sec_user_agent())
        embedding_client = GeminiEmbeddingClient(settings.require_gemini_api_key())

        store = await _build_eval_store(
            _available_loaders(corpus_loaders(sec_client), GPW_COMPANIES),
            llm_client=llm_client,
            prompt_registry=prompt_registry,
            model=model,
            embedding_client=embedding_client,
        )
        _store = store
        return store


def _available_loaders(
    loaders: dict[str, ChunkLoader], gpw_pdfs: dict[str, Path]
) -> dict[str, ChunkLoader]:
    # data/private/gpw/ is gitignored — a real broker/IR download the owner
    # has locally, not something every machine running this eval
    # necessarily has. Left out quietly, not reported as a failure.
    return {
        company: load
        for company, load in loaders.items()
        if company not in gpw_pdfs or gpw_pdfs[company].exists()
    }


async def _build_eval_store(loaders: dict[str, ChunkLoader], **build_kwargs) -> VectorStore:
    """The same index.builder.build_index the `filings-rag build-index`
    command saves (#255), so the eval measures the index the web app
    searches. Stricter than the command, though: a company that failed
    (Gemini 503/429, SEC unreachable) stops the eval instead of being
    skipped."""
    result = await build_index(loaders, embedding_model=EMBEDDING_MODEL, **build_kwargs)
    failures = [
        status
        for status in result.statuses
        if status.skipped_reason not in (None, NO_CHUNKS_REASON)
    ]
    if failures:
        raise EvalIndexIncompleteError(failures)
    return result.store


async def _retrieve_and_rerank(question: str, ctx: RunContext, model: str) -> RetrievalResult:
    store = await _get_store(ctx.llm_client, ctx.prompts, model)
    settings = Settings()
    embedding_client = GeminiEmbeddingClient(settings.require_gemini_api_key())

    hybrid_result = await retrieve_hybrid(
        question,
        store,
        embedding_client=embedding_client,
        embedding_model=EMBEDDING_MODEL,
        known_companies=list(US_COMPANIES) + list(GPW_COMPANIES),
        top_k=RERANK_CANDIDATE_POOL,
    )
    reranked = await rerank(question, hybrid_result.chunks, ctx.llm_client, ctx.prompts, model)
    final_chunks = reranked[:DEFAULT_TOP_K]

    return RetrievalResult(
        chunks=final_chunks,
        top_score=final_chunks[0].score if final_chunks else 0.0,
        company_in_corpus=hybrid_result.company_in_corpus,
    )


async def retrieval_target(case_input: dict, ctx: RunContext) -> dict:
    model = ctx.model or "gemini-3.6-flash"
    result = await _retrieve_and_rerank(case_input["question"], ctx, model)

    return {
        "top_1_company": result.chunks[0].chunk.company if result.chunks else None,
        "top_score": result.top_score,
        "company_in_corpus": result.company_in_corpus,
        "companies_retrieved": [retrieved.chunk.company for retrieved in result.chunks],
        "sections_retrieved": [retrieved.chunk.section for retrieved in result.chunks],
    }


async def answer_target(case_input: dict, ctx: RunContext) -> dict:
    model = ctx.model or "gemini-3.6-flash"
    retrieval = await _retrieve_and_rerank(case_input["question"], ctx, model)
    answer = await build_answer(
        case_input["question"], retrieval, ctx.llm_client, ctx.prompts, model
    )
    return {
        "text": answer.text,
        "refused": answer.refused,
        "refusal_reason": answer.refusal_reason,
        "citation_count": len(answer.citations),
        "has_citations": bool(answer.citations),
    }


async def web_answer_target(case_input: dict, ctx: RunContext) -> dict:
    """answer_target's cases through the web app's pipeline (#225): the
    index saved by `filings-rag build-index`, one query embedding and no LLM
    reranker. Comparing p2-web-answer-accuracy with p2-answer-accuracy
    shows what dropping the reranker costs. Re-run with --no-cache after a
    rebuild: the eval cache doesn't know the saved index changed."""
    model = ctx.model or "gemini-3.6-flash"
    index = load_index()
    if index is None:
        raise RuntimeError("No saved filings index, run `fin-ai-lab filings-rag build-index` first")

    settings = Settings()
    answer = await ask(
        case_input["question"],
        index,
        company=None,
        llm_client=ctx.llm_client,
        embedding_client=GeminiEmbeddingClient(settings.require_gemini_api_key()),
        prompt_registry=ctx.prompts,
        model=model,
    )
    return {
        "text": answer.text,
        "refused": answer.refused,
        "refusal_reason": answer.refusal_reason,
        "citation_count": len(answer.citations),
        "has_citations": bool(answer.citations),
    }
