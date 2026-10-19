import asyncio
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from google import genai
from google.genai import types
from pydantic import BaseModel

from fin_ai_lab.core.errors import UnknownModelError
from fin_ai_lab.core.llm.pricing import PRICES
from fin_ai_lab.core.llm.trace import TraceSink, TraceSpan


class EmbeddingResult(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    vectors: list[list[float]]
    cost_usd: Decimal


class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str], model: str) -> EmbeddingResult: ...


# BatchEmbedContentsRequest rejects more than 100 items per call ("at most
# 100 requests can be in one batch"). Kept well under that: a live call with
# exactly 100 items 429s immediately while a 1-item call succeeds, so the
# free-tier quota named "EmbedContentRequestsPerMinutePerUserPerProjectPer
# Model-FreeTier" (quotaValue 100) counts each *text* in the batch, not each
# API call — all verified empirically 2026-09-16, undocumented on
# ai.google.dev. Smaller batches pace this more smoothly than one huge one.
MAX_BATCH_SIZE = 20
# 60s / 80 items — 80, not the observed 100, for headroom against jitter.
DEFAULT_SECONDS_PER_ITEM = 60 / 80


def _estimate_tokens(texts: list[str]) -> int:
    # embed_content's response has no usage/statistics field (verified
    # empirically against the real API 2026-09-16, both embeddings.metadata
    # and ContentEmbedding.statistics come back None) — chars/4 is a rough
    # estimate, good enough for the zero-cost fail-safe guard, not billing.
    return sum(len(t) for t in texts) // 4


class GeminiEmbeddingClient:
    def __init__(
        self,
        api_key: str,
        trace_sink: TraceSink | None = None,
        seconds_per_item: float = DEFAULT_SECONDS_PER_ITEM,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._trace_sink = trace_sink or TraceSink()
        self.total_cost_usd = Decimal(0)
        self._seconds_per_item = seconds_per_item
        self._last_call_at: float | None = None
        self._required_wait_s = 0.0
        self._throttle_lock = asyncio.Lock()

    async def _throttle(self) -> None:
        # Paced by the PREVIOUS batch's size: sending N items means the next
        # call must wait N * seconds_per_item, capping average throughput
        # rather than just spacing out calls regardless of their size.
        async with self._throttle_lock:
            if self._last_call_at is not None:
                remaining = self._required_wait_s - (time.monotonic() - self._last_call_at)
                if remaining > 0:
                    await asyncio.sleep(remaining)

    async def embed(self, texts: list[str], model: str) -> EmbeddingResult:
        if PRICES.get(model) is None:
            raise UnknownModelError(model)

        vectors: list[list[float]] = []
        total_cost_usd = Decimal(0)
        for start in range(0, len(texts), MAX_BATCH_SIZE):
            batch = texts[start : start + MAX_BATCH_SIZE]
            result = await self._embed_batch(batch, model)
            vectors.extend(result.vectors)
            total_cost_usd += result.cost_usd

        self.total_cost_usd += total_cost_usd
        return EmbeddingResult(vectors=vectors, cost_usd=total_cost_usd)

    async def _embed_batch(self, texts: list[str], model: str) -> EmbeddingResult:
        price = PRICES[model]

        trace_id = uuid.uuid4().hex
        span_id = uuid.uuid4().hex
        started_at = time.monotonic()
        # Wrapped as separate Content objects: a plain list of strings makes
        # the API aggregate everything into a single embedding instead of
        # one per text (verified empirically 2026-09-16, gemini-embedding-2).
        contents = [types.Content(parts=[types.Part(text=t)]) for t in texts]

        await self._throttle()
        self._last_call_at = time.monotonic()
        self._required_wait_s = len(texts) * self._seconds_per_item
        try:
            response = await self._client.aio.models.embed_content(model=model, contents=contents)
        except Exception as exc:
            self._trace_sink.write(
                TraceSpan(
                    trace_id=trace_id,
                    span_id=span_id,
                    ts=datetime.now(UTC),
                    kind="embedding",
                    name="embed",
                    model=model,
                    latency_ms=int((time.monotonic() - started_at) * 1000),
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            raise

        latency_ms = int((time.monotonic() - started_at) * 1000)
        vectors = [list(embedding.values) for embedding in response.embeddings]
        estimated_tokens = _estimate_tokens(texts)
        cost_usd = price.cost_usd(estimated_tokens, 0)

        self._trace_sink.write(
            TraceSpan(
                trace_id=trace_id,
                span_id=span_id,
                ts=datetime.now(UTC),
                kind="embedding",
                name="embed",
                model=model,
                usage={"estimated_tokens": estimated_tokens},
                cost_usd=cost_usd,
                latency_ms=latency_ms,
            )
        )

        return EmbeddingResult(vectors=vectors, cost_usd=cost_usd)
