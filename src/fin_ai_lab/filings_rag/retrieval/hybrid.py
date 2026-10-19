import bm25s

from fin_ai_lab.core.llm.embeddings import EmbeddingClient
from fin_ai_lab.filings_rag.index.store import VectorStore
from fin_ai_lab.filings_rag.models import Chunk, RetrievalResult, RetrievedChunk

DEFAULT_TOP_K = 5

# ASSUMPTION (03-design.md P2-S3, user decision): exact word/number/company
# -name matches (BM25) matter more for financial data than topical semantic
# similarity (embeddings) — a chunk that names the wrong company but reads
# on-topic is a worse match than one with the right name and a plainer
# sentence. Weighted higher, not exclusive. Revisit against
# p2-retrieval-accuracy once that eval covers hybrid, same as
# retrieval.naive.DEFAULT_REFUSAL_THRESHOLD was calibrated in S2.
BM25_WEIGHT = 0.65
EMBEDDING_WEIGHT = 0.35


async def retrieve_hybrid(
    query: str,
    store: VectorStore,
    *,
    embedding_client: EmbeddingClient,
    embedding_model: str,
    known_companies: list[str] | None = None,
    top_k: int = DEFAULT_TOP_K,
    company: str | None = None,
    fiscal_period: str | None = None,
) -> RetrievalResult:
    company_in_corpus = _mentions_known_company(query, known_companies) if known_companies else True

    result = await embedding_client.embed([query], model=embedding_model)
    candidates = _filter(store.score_all(result.vectors[0]), company, fiscal_period)
    if not candidates:
        return RetrievalResult(chunks=[], top_score=0.0, company_in_corpus=company_in_corpus)

    chunks = [chunk for chunk, _ in candidates]
    embedding_scores = _min_max_normalize([score for _, score in candidates])
    bm25_scores = _min_max_normalize(_bm25_scores(query, chunks))

    fused = [
        BM25_WEIGHT * bm25 + EMBEDDING_WEIGHT * embedding
        for bm25, embedding in zip(bm25_scores, embedding_scores, strict=True)
    ]
    ranked = sorted(zip(chunks, fused, strict=True), key=lambda pair: pair[1], reverse=True)[:top_k]
    retrieved = [RetrievedChunk(chunk=chunk, score=score) for chunk, score in ranked]

    return RetrievalResult(
        chunks=retrieved,
        top_score=retrieved[0].score if retrieved else 0.0,
        company_in_corpus=company_in_corpus,
    )


def _filter(
    scored: list[tuple[Chunk, float]], company: str | None, fiscal_period: str | None
) -> list[tuple[Chunk, float]]:
    return [
        (chunk, score)
        for chunk, score in scored
        if (company is None or chunk.company == company)
        and (fiscal_period is None or chunk.fiscal_period == fiscal_period)
    ]


def _bm25_scores(query: str, chunks: list[Chunk]) -> list[float]:
    # return_ids=False: plain word lists in and out, so the query is scored
    # against the same vocabulary as the freshly built per-request corpus
    # index below, instead of a separate token-id space (bm25s 0.3.11).
    corpus_tokens = bm25s.tokenize(
        [chunk.text for chunk in chunks], show_progress=False, return_ids=False
    )
    retriever = bm25s.BM25()
    retriever.index(corpus_tokens, show_progress=False)
    query_tokens = bm25s.tokenize([query], show_progress=False, return_ids=False)
    return list(retriever.get_scores(query_tokens[0]))


def _min_max_normalize(values: list[float]) -> list[float]:
    if not values:
        return values
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def _mentions_known_company(query: str, known_companies: list[str]) -> bool:
    lowered = query.lower()
    return any(company.lower() in lowered for company in known_companies)
