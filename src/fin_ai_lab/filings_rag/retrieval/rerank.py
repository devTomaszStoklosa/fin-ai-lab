import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag.models import RetrievedChunk

CACHE_DIR = Path("data/cache/rerank")


class _RerankItem(BaseModel):
    chunk_id: str
    relevance_score: float


class _RerankDraft(BaseModel):
    scores: list[_RerankItem]


async def rerank(
    query: str,
    candidates: list[RetrievedChunk],
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    *,
    cache_dir: Path = CACHE_DIR,
) -> list[RetrievedChunk]:
    """Re-scores candidates with an LLM judge and re-orders them (03-design.md
    P2-S3, retrieval.rerank contract).

    Result cached on disk per (model, query, candidate set) — same disk-cache
    pattern as index.embeddings.embed_with_cache — so a repeated query never
    pays for a second LLM call."""
    if not candidates:
        return []

    model_cache_dir = cache_dir / model
    model_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = model_cache_dir / f"{_cache_key(query, candidates)}.json"

    if cache_path.exists():
        scores = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        scores = await _score_with_llm(query, candidates, llm_client, prompt_registry, model)
        if scores is None:
            return candidates
        cache_path.write_text(json.dumps(scores), encoding="utf-8")

    return _reorder(candidates, scores)


async def _score_with_llm(
    query: str,
    candidates: list[RetrievedChunk],
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
) -> dict[str, float] | None:
    payload = [_candidate_payload(retrieved) for retrieved in candidates]
    prompt = prompt_registry.get("rerank", 1)
    candidates_json = json.dumps(payload, ensure_ascii=False)
    rendered = prompt.render(question=query, candidates_json=candidates_json)

    request = LlmRequest(
        model=model,
        messages=[{"role": "user", "text": rendered}],
        response_schema=_RerankDraft,
        prompt_id="rerank",
        prompt_version=1,
    )
    result = await llm_client.complete(request)
    draft = result.parsed
    if not isinstance(draft, _RerankDraft):
        return None

    return {item.chunk_id: item.relevance_score for item in draft.scores}


def _reorder(candidates: list[RetrievedChunk], scores: dict[str, float]) -> list[RetrievedChunk]:
    # A chunk_id the model failed to score keeps its incoming (hybrid) score
    # instead of being dropped or sunk to the bottom — a rerank miss on one
    # candidate shouldn't discard it from consideration.
    rescored = [
        RetrievedChunk(chunk=retrieved.chunk, score=scores.get(retrieved.chunk.id, retrieved.score))
        for retrieved in candidates
    ]
    return sorted(rescored, key=lambda retrieved: retrieved.score, reverse=True)


def _candidate_payload(retrieved: RetrievedChunk) -> dict:
    return {
        "chunk_id": retrieved.chunk.id,
        "company": retrieved.chunk.company,
        "filing_type": retrieved.chunk.filing_type,
        "fiscal_period": retrieved.chunk.fiscal_period,
        "section": retrieved.chunk.section,
        "text": retrieved.chunk.text,
    }


def _cache_key(query: str, candidates: list[RetrievedChunk]) -> str:
    candidate_ids = ",".join(sorted(retrieved.chunk.id for retrieved in candidates))
    return hashlib.sha256(f"{query}|{candidate_ids}".encode()).hexdigest()
