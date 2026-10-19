from fin_ai_lab.core.llm.embeddings import EmbeddingClient
from fin_ai_lab.filings_rag.index.store import VectorStore
from fin_ai_lab.filings_rag.models import RetrievalResult, RetrievedChunk

DEFAULT_TOP_K = 5
# ASSUMPTION (03-design.md, open question #1): starting point, not a
# measured value — calibrate against the golden set in this same slice
# (p2-retrieval-accuracy) before trusting it.
DEFAULT_REFUSAL_THRESHOLD = 0.5


async def retrieve(
    query: str,
    store: VectorStore,
    *,
    embedding_client: EmbeddingClient,
    embedding_model: str,
    known_companies: list[str] | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> RetrievalResult:
    result = await embedding_client.embed([query], model=embedding_model)
    matches = store.search(result.vectors[0], top_k=top_k)

    retrieved = [RetrievedChunk(chunk=chunk, score=score) for chunk, score in matches]
    top_score = retrieved[0].score if retrieved else 0.0
    company_in_corpus = (
        _mentions_known_company(query, known_companies) if known_companies else True
    )

    return RetrievalResult(
        chunks=retrieved, top_score=top_score, company_in_corpus=company_in_corpus
    )


def _mentions_known_company(query: str, known_companies: list[str]) -> bool:
    lowered = query.lower()
    return any(company.lower() in lowered for company in known_companies)
