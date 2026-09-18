import uuid
from decimal import Decimal

from pydantic import BaseModel

from fin_ai_lab.core.llm.client import LlmRequest, LlmResult, TokenUsage
from fin_ai_lab.core.llm.embeddings import EmbeddingResult


class FakeLlmClient:
    def __init__(
        self, responses: dict[str, str], tool_calls: dict[str, list[str]] | None = None
    ) -> None:
        self._responses = responses
        self._tool_calls = tool_calls or {}
        self.requests: list[LlmRequest] = []
        self.total_cost_usd = Decimal(0)

    async def complete(self, request: LlmRequest) -> LlmResult:
        self.requests.append(request)
        key = request.prompt_id or request.model
        text = self._responses[key]

        parsed: BaseModel | None = None
        if request.response_schema is not None:
            parsed = request.response_schema.model_validate_json(text)

        return LlmResult(
            text=text,
            parsed=parsed,
            finish_reason="STOP",
            incomplete=False,
            usage=TokenUsage(input_tokens=0, output_tokens=0),
            cost_usd=Decimal(0),
            latency_ms=0,
            trace_id=uuid.uuid4().hex,
            span_id=uuid.uuid4().hex,
            tool_calls=self._tool_calls.get(key, []),
        )


class FakeEmbeddingClient:
    def __init__(self, dim: int = 8) -> None:
        self._dim = dim
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str], model: str) -> EmbeddingResult:
        self.calls.append(texts)
        return EmbeddingResult(
            vectors=[_deterministic_vector(text, self._dim) for text in texts],
            cost_usd=Decimal(0),
        )


def _deterministic_vector(text: str, dim: int) -> list[float]:
    # Same text -> same vector (for cache-hit tests), different text -> a
    # different vector — not a real embedding, just enough to exercise
    # cosine similarity and caching without a network call.
    seed = sum(ord(char) for char in text) or 1
    return [((seed * (index + 1)) % 97) / 97 for index in range(dim)]
