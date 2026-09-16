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


def _estimate_tokens(texts: list[str]) -> int:
    # embed_content's response has no usage/statistics field (verified
    # empirically against the real API 2026-09-16, both embeddings.metadata
    # and ContentEmbedding.statistics come back None) — chars/4 is a rough
    # estimate, good enough for the zero-cost fail-safe guard, not billing.
    return sum(len(t) for t in texts) // 4


class GeminiEmbeddingClient:
    def __init__(self, api_key: str, trace_sink: TraceSink | None = None) -> None:
        self._client = genai.Client(api_key=api_key)
        self._trace_sink = trace_sink or TraceSink()
        self.total_cost_usd = Decimal(0)

    async def embed(self, texts: list[str], model: str) -> EmbeddingResult:
        price = PRICES.get(model)
        if price is None:
            raise UnknownModelError(model)

        trace_id = uuid.uuid4().hex
        span_id = uuid.uuid4().hex
        started_at = time.monotonic()
        # Wrapped as separate Content objects: a plain list of strings makes
        # the API aggregate everything into a single embedding instead of
        # one per text (verified empirically 2026-09-16, gemini-embedding-2).
        contents = [types.Content(parts=[types.Part(text=t)]) for t in texts]

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
        self.total_cost_usd += cost_usd

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
