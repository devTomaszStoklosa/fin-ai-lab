from pathlib import Path

import httpx
from google.genai import errors as genai_errors
from pydantic import BaseModel

from fin_ai_lab.core.errors import ResponseValidationError
from fin_ai_lab.core.llm.client import LlmClient
from fin_ai_lab.core.llm.embeddings import EmbeddingClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag.corpus import ChunkLoader
from fin_ai_lab.filings_rag.index.embeddings import CACHE_DIR as EMBEDDING_CACHE_DIR
from fin_ai_lab.filings_rag.index.embeddings import embed_with_cache
from fin_ai_lab.filings_rag.index.store import VectorStore
from fin_ai_lab.filings_rag.retrieval.contextual import CACHE_DIR as CONTEXTUAL_CACHE_DIR
from fin_ai_lab.filings_rag.retrieval.contextual import contextualize

# Failures that are about one company's source or today's provider state
# (Gemini quota/overload, SEC unreachable, a GPW PDF missing on this
# machine, a malformed model response) — skip that company and keep going.
# Anything else (a bug, BudgetExceeded) still stops the whole build.
_SKIPPABLE_ERRORS = (
    genai_errors.APIError,
    ResponseValidationError,
    httpx.HTTPError,
    OSError,
)

# skipped_reason of a company whose source was read fine but held nothing
# to index — not an error (qa_target's eval tells the two apart).
NO_CHUNKS_REASON = "no chunks found"


class CompanyBuildStatus(BaseModel):
    company: str
    chunk_count: int = 0
    # None: the company is in the index.
    skipped_reason: str | None = None


class IndexBuildResult(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    store: VectorStore
    statuses: list[CompanyBuildStatus]


async def build_index(
    loaders: dict[str, ChunkLoader],
    *,
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    embedding_client: EmbeddingClient,
    embedding_model: str,
    contextual_cache_dir: Path = CONTEXTUAL_CACHE_DIR,
    embedding_cache_dir: Path = EMBEDDING_CACHE_DIR,
) -> IndexBuildResult:
    """Builds the index company by company (#253). A company that fails is
    reported and skipped instead of failing the whole build — with only 20
    Gemini calls a day (docs/LLM-API.md), a full corpus may take several
    days. Every step is disk-cached (SEC downloads, contextualize, embed),
    so re-running only pays for what's still missing; a company finished
    yesterday is rebuilt from cache without any network or model call."""
    store = VectorStore()
    statuses: list[CompanyBuildStatus] = []

    for company, load in loaders.items():
        try:
            chunks = await load()
            if not chunks:
                statuses.append(
                    CompanyBuildStatus(company=company, skipped_reason=NO_CHUNKS_REASON)
                )
                continue

            # One LLM call per document situates every chunk at once
            # (03-design.md P2-S4). The context sentence is embedded together
            # with the chunk, but chunk.text itself stays unchanged for
            # citation faithfulness (answer.verify matches excerpts against
            # the raw chunk, not the contextualized version).
            contexts = await contextualize(
                chunks, llm_client, prompt_registry, model, cache_dir=contextual_cache_dir
            )
            contextualized_texts = [
                f"{contexts.get(chunk.id, '')}\n\n{chunk.text}".strip() for chunk in chunks
            ]
            vectors = await embed_with_cache(
                contextualized_texts,
                model=embedding_model,
                embedding_client=embedding_client,
                cache_dir=embedding_cache_dir,
            )
        except _SKIPPABLE_ERRORS as exc:
            statuses.append(
                CompanyBuildStatus(company=company, skipped_reason=f"{type(exc).__name__}: {exc}")
            )
            continue

        store.add(chunks, vectors)
        statuses.append(CompanyBuildStatus(company=company, chunk_count=len(chunks)))

    return IndexBuildResult(store=store, statuses=statuses)
