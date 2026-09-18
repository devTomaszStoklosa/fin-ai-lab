import asyncio
from pathlib import Path

from fin_ai_lab.core.config import Settings
from fin_ai_lab.core.evals.models import RunContext
from fin_ai_lab.core.llm.client import LlmClient
from fin_ai_lab.core.llm.embeddings import GeminiEmbeddingClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag.answer.builder import build_answer
from fin_ai_lab.filings_rag.index.embeddings import embed_with_cache
from fin_ai_lab.filings_rag.index.store import VectorStore
from fin_ai_lab.filings_rag.ingest.gpw_pdf import parse_gpw_report
from fin_ai_lab.filings_rag.ingest.sec_edgar import SecEdgarClient
from fin_ai_lab.filings_rag.models import RetrievalResult
from fin_ai_lab.filings_rag.retrieval.contextual import contextualize
from fin_ai_lab.filings_rag.retrieval.hybrid import DEFAULT_TOP_K, retrieve_hybrid
from fin_ai_lab.filings_rag.retrieval.rerank import rerank

EMBEDDING_MODEL = "gemini-embedding-2"
# Wider recall pool for the reranker to work with than the final answer
# needs (03-design.md P2-S3) — hybrid search casts a broader net, rerank
# narrows it back down to DEFAULT_TOP_K before the refusal-threshold check.
RERANK_CANDIDATE_POOL = 15

# US_COMPANIES only for now — GPW (Atrem, PKN Orlen, ING BSK) join once their
# annual report PDFs are manually downloaded into data/private/gpw/
# (02-spec.md), same corpus as resolved in the P2 BA spec.
US_COMPANIES = {
    "Microsoft": "789019",
    "Amazon": "1018724",
    "Oracle": "1341439",
    "Citigroup": "831001",
    "NextEra Energy": "753308",
}

# GPW half-year reports (data/private/gpw/, gitignored real broker/IR
# downloads — 01-story.md resolved corpus, P2-S7). One narrative file per
# company: the others in each folder are audit opinions/financial
# statements without prose to retrieve. Chosen by inspecting real page
# counts/content, not guessed. No _SECTION_FILTER applies to these (Polish
# reports have no "Item 1A Risk Factors" equivalent) — the whole narrative
# report is indexed.
GPW_COMPANIES: dict[str, Path] = {
    "Atrem": Path("data/private/gpw/Atrem/Atrem 1H2026 Sprawozdanie zarządu.pdf"),
    "ING Bank Śląski": Path(
        "data/private/gpw/ING/Sprawozdanie_Zarzadu_z_dzialalnosci_Grupy_ING_Bank_Slaski_SA_Ipol_2026_PL.pdf"
    ),
    "PKN Orlen": Path("data/private/gpw/Orlen/ORLEN_260806_2026półrocze - RAPORT IH2026.pdf"),
}
GPW_FISCAL_PERIOD = "1H2026"

# ASSUMPTION for this golden set (revisit for a real "index everything"
# command, not built yet): only Risk Factors, not the full 10-K. The free
# tier for gemini-embedding-2 turned out to cap at ~100 embedded *texts* per
# minute regardless of how many API calls that's split into (verified
# empirically 2026-09-16, undocumented) — indexing all ~400 chunks per
# company x 5 companies would take ~20+ minutes. One rich, real section per
# company is enough to exercise retrieval/citations/refusal meaningfully.
_SECTION_FILTER = "risk factors"

# Built once per process and reused across every case in an eval run — the
# eval harness only tracks cost via ctx.llm_client, so building the index
# (SEC fetch + embeddings) here instead of on every case keeps that cost
# accounting meaningful: after the first real run this is a disk-cache-only
# rebuild (no network, no billed tokens), and no core.evals contract needed
# an embedding-client-aware cost path just for this one target.
_build_lock = asyncio.Lock()
_store: VectorStore | None = None


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

        store = VectorStore()
        for company, cik in US_COMPANIES.items():
            all_chunks = await sec_client.ingest_10k(cik, company)
            chunks = [c for c in all_chunks if _SECTION_FILTER in c.section.lower()]
            if not chunks:
                continue

            # One LLM call per company (not per chunk) situates every chunk
            # within the whole "risk factors" section at once (03-design.md
            # P2-S4) — embedding the context + chunk together, but keeping
            # chunk.text itself unchanged for citation faithfulness
            # (answer.verify.verify_citations_faithful matches excerpts
            # against the raw chunk, not the contextualized version).
            contexts = await contextualize(chunks, llm_client, prompt_registry, model)
            contextualized_texts = [
                f"{contexts.get(chunk.id, '')}\n\n{chunk.text}".strip() for chunk in chunks
            ]
            vectors = await embed_with_cache(
                contextualized_texts,
                model=EMBEDDING_MODEL,
                embedding_client=embedding_client,
            )
            store.add(chunks, vectors)

        for company, pdf_path in GPW_COMPANIES.items():
            if not pdf_path.exists():
                # data/private/gpw/ is gitignored — a real broker/IR
                # download the owner has locally, not something every
                # machine running this eval necessarily has.
                continue

            chunks = parse_gpw_report(
                pdf_path, company=company, fiscal_period=GPW_FISCAL_PERIOD, period_type="half-year"
            )
            if not chunks:
                continue

            contexts = await contextualize(chunks, llm_client, prompt_registry, model)
            contextualized_texts = [
                f"{contexts.get(chunk.id, '')}\n\n{chunk.text}".strip() for chunk in chunks
            ]
            vectors = await embed_with_cache(
                contextualized_texts,
                model=EMBEDDING_MODEL,
                embedding_client=embedding_client,
            )
            store.add(chunks, vectors)

        _store = store
        return store


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
