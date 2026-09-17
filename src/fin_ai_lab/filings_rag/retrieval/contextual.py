import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag.models import Chunk

CACHE_DIR = Path("data/cache/contextual")

# Schema JSON overhead (chunk_id + punctuation) on top of a short context
# sentence, times the largest company's chunk count seen so far (Oracle,
# 136) — default 16_000 risked truncating the batch response.
MAX_OUTPUT_TOKENS = 24_000


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
    """One LLM call for the whole document situates every chunk at once
    (03-design.md P2-S4), not one call per chunk — the current corpus alone
    has 443 chunks, and gemini-3.6-flash's free tier allows only 20
    generate_content calls a day (docs/LLM-API.md), so per-chunk calls
    aren't an option.

    Cached on disk per (model, document contents) — same disk-cache pattern
    as index.embeddings.embed_with_cache and retrieval.rerank — so
    re-running against an unchanged filing never pays for a second LLM
    call. Gemini's own context caching (cachedContent/TTL) isn't used: at
    one call per document there's nothing left to cache server-side that
    this doesn't already cover more simply and durably."""
    if not chunks:
        return {}

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
