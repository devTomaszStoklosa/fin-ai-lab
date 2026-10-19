import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag.models import Chunk

CACHE_DIR = Path("data/cache/contextual")

# One call per whole document (Oracle, the largest US filing, 136 chunks)
# used to risk truncating the batch response at the old 16_000 default.
# Now covers CONTEXTUALIZE_BATCH_SIZE-sized batches with room to spare —
# left unchanged rather than tightened, since over-provisioning it is free.
MAX_OUTPUT_TOKENS = 24_000

# One call per whole document (03-design.md P2-S4's original design) broke
# down once the corpus grew past the ~443 chunks it was sized for: PKN
# Orlen alone is 399 chunks / ~440K characters, and Gemini started
# rejecting even the smallest document in the corpus (Atrem, 59 chunks)
# with a persistent 503 (not a momentary spike -- reproduced 4x, including
# after a retry-with-backoff fix) -- see issue for the P2 contextualize
# 503. Batching trades some context quality for correctness: a chunk's
# context is now grounded only in its own batch, not the whole document
# (03-design.md's "chunks reveal about the document as a whole" is now
# "reveal about this batch"). Not yet verified live against Gemini's real
# per-request size limit -- picked conservatively, to be tuned after a live
# check.
CONTEXTUALIZE_BATCH_SIZE = 10


class _ContextItem(BaseModel):
    chunk_id: str
    context: str


class _ContextDraft(BaseModel):
    contexts: list[_ContextItem]


async def contextualize(
    chunks: list[Chunk],
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    *,
    cache_dir: Path = CACHE_DIR,
) -> dict[str, str]:
    """One LLM call per CONTEXTUALIZE_BATCH_SIZE-sized batch of a document's
    chunks (not one call per whole document, and not one call per chunk —
    see CONTEXTUALIZE_BATCH_SIZE's comment for why), so every chunk still
    gets a situating context without a single oversized request.

    Cached on disk per (model, batch contents) — same disk-cache pattern as
    index.embeddings.embed_with_cache and retrieval.rerank — so re-running
    against an unchanged filing never pays for a second LLM call. Caching
    per batch, not per whole document, also means a run interrupted midway
    through a large filing (daily quota exhausted, docs/LLM-API.md) resumes
    from the last completed batch instead of re-paying for the whole
    document. Gemini's own context caching (cachedContent/TTL) isn't used:
    this already covers the same need more simply and durably."""
    if not chunks:
        return {}

    contexts: dict[str, str] = {}
    for start in range(0, len(chunks), CONTEXTUALIZE_BATCH_SIZE):
        batch = chunks[start : start + CONTEXTUALIZE_BATCH_SIZE]
        batch_contexts = await _contextualize_batch(
            batch, llm_client, prompt_registry, model, cache_dir
        )
        contexts.update(batch_contexts)
    return contexts


async def _contextualize_batch(
    chunks: list[Chunk],
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    cache_dir: Path,
) -> dict[str, str]:
    model_cache_dir = cache_dir / model
    model_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = model_cache_dir / f"{_cache_key(chunks)}.json"

    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    contexts = await _contextualize_with_llm(chunks, llm_client, prompt_registry, model)
    cache_path.write_text(json.dumps(contexts), encoding="utf-8")
    return contexts


async def _contextualize_with_llm(
    chunks: list[Chunk], llm_client: LlmClient, prompt_registry: PromptRegistry, model: str
) -> dict[str, str]:
    payload = [{"chunk_id": chunk.id, "text": chunk.text} for chunk in chunks]
    chunks_json = json.dumps(payload, ensure_ascii=False)
    prompt = prompt_registry.get("contextual", 1)
    rendered = prompt.render(
        company=chunks[0].company,
        filing_type=chunks[0].filing_type,
        fiscal_period=chunks[0].fiscal_period,
        chunks_json=chunks_json,
    )

    request = LlmRequest(
        model=model,
        messages=[{"role": "user", "text": rendered}],
        max_output_tokens=MAX_OUTPUT_TOKENS,
        response_schema=_ContextDraft,
        prompt_id="contextual",
        prompt_version=1,
    )
    result = await llm_client.complete(request)
    draft = result.parsed
    if not isinstance(draft, _ContextDraft):
        return {}

    return {item.chunk_id: item.context for item in draft.contexts}


def _cache_key(chunks: list[Chunk]) -> str:
    # Hashes id + text per chunk, not just ids — invalidates the cache if
    # the source filing's content changes, not only if chunk boundaries do.
    fingerprint = "|".join(f"{chunk.id}:{chunk.text}" for chunk in chunks)
    return hashlib.sha256(fingerprint.encode()).hexdigest()
