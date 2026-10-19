import json
import uuid
from decimal import Decimal
from pathlib import Path

from fin_ai_lab.core.llm.client import LlmRequest, LlmResult, TokenUsage
from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag.models import Chunk
from fin_ai_lab.filings_rag.retrieval.contextual import (
    CONTEXTUALIZE_BATCH_SIZE,
    contextualize,
)

PROMPTS_DIR = Path("src/fin_ai_lab/filings_rag/prompts")
MODEL = "gemini-3.6-flash"


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


class _SequencedLlmClient:
    """Returns responses.pop(0) per call, unlike FakeLlmClient's one fixed
    response per prompt_id -- needed to give each batch in a multi-batch
    contextualize() call a distinct, verifiable set of chunk_ids."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.requests: list[LlmRequest] = []

    async def complete(self, request: LlmRequest) -> LlmResult:
        self.requests.append(request)
        text = self._responses.pop(0)
        parsed = (
            request.response_schema.model_validate_json(text)
            if request.response_schema is not None
            else None
        )
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
        )


def _chunk(chunk_id: str, text: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        company="Oracle",
        filing_type="10-K",
        fiscal_period="FY2025",
        section="ITEM 1A. RISK FACTORS",
        text=text,
        source_location="https://example.test/filing.htm",
        language="en",
    )


async def test_contextualize_returns_a_context_per_chunk_in_one_llm_call(tmp_path: Path) -> None:
    draft = (
        '{"contexts": [{"chunk_id": "a", "context": "About cloud strategy."}, '
        '{"chunk_id": "b", "context": "About data center capacity."}]}'
    )
    llm_client = FakeLlmClient({"contextual": draft})
    chunks = [_chunk("a", "cloud text"), _chunk("b", "data center text")]

    contexts = await contextualize(
        chunks, llm_client, _prompt_registry(), MODEL, cache_dir=tmp_path
    )

    assert contexts == {"a": "About cloud strategy.", "b": "About data center capacity."}
    assert len(llm_client.requests) == 1


async def test_contextualize_caches_the_result_and_skips_a_second_llm_call(tmp_path: Path) -> None:
    draft = '{"contexts": [{"chunk_id": "a", "context": "About cloud strategy."}]}'
    llm_client = FakeLlmClient({"contextual": draft})
    chunks = [_chunk("a", "cloud text")]

    await contextualize(chunks, llm_client, _prompt_registry(), MODEL, cache_dir=tmp_path)
    await contextualize(chunks, llm_client, _prompt_registry(), MODEL, cache_dir=tmp_path)

    assert len(llm_client.requests) == 1


async def test_contextualize_returns_empty_dict_without_calling_the_llm() -> None:
    llm_client = FakeLlmClient({})  # would KeyError if ever called

    contexts = await contextualize([], llm_client, _prompt_registry(), MODEL)

    assert contexts == {}


async def test_contextualize_splits_more_chunks_than_batch_size_into_multiple_calls(
    tmp_path: Path,
) -> None:
    chunks = [_chunk(str(i), f"text {i}") for i in range(CONTEXTUALIZE_BATCH_SIZE + 1)]
    first_batch_draft = json.dumps(
        {
            "contexts": [
                {"chunk_id": str(i), "context": f"context {i}"}
                for i in range(CONTEXTUALIZE_BATCH_SIZE)
            ]
        }
    )
    second_batch_draft = json.dumps(
        {"contexts": [{"chunk_id": str(CONTEXTUALIZE_BATCH_SIZE), "context": "context last"}]}
    )
    llm_client = _SequencedLlmClient([first_batch_draft, second_batch_draft])

    contexts = await contextualize(
        chunks, llm_client, _prompt_registry(), MODEL, cache_dir=tmp_path
    )

    assert len(llm_client.requests) == 2
    assert len(contexts) == CONTEXTUALIZE_BATCH_SIZE + 1
    assert contexts[str(CONTEXTUALIZE_BATCH_SIZE)] == "context last"


async def test_contextualize_resumes_from_a_partially_cached_document(tmp_path: Path) -> None:
    # Simulates a run interrupted after the first batch (e.g. the daily
    # quota ran out) -- re-running must not re-pay for the cached batch.
    chunks = [_chunk(str(i), f"text {i}") for i in range(CONTEXTUALIZE_BATCH_SIZE + 1)]
    first_batch_draft = json.dumps(
        {
            "contexts": [
                {"chunk_id": str(i), "context": f"context {i}"}
                for i in range(CONTEXTUALIZE_BATCH_SIZE)
            ]
        }
    )
    second_batch_draft = json.dumps(
        {"contexts": [{"chunk_id": str(CONTEXTUALIZE_BATCH_SIZE), "context": "context last"}]}
    )
    first_run_client = _SequencedLlmClient([first_batch_draft])
    await contextualize(
        chunks[:CONTEXTUALIZE_BATCH_SIZE],
        first_run_client,
        _prompt_registry(),
        MODEL,
        cache_dir=tmp_path,
    )

    second_run_client = _SequencedLlmClient([second_batch_draft])
    contexts = await contextualize(
        chunks, second_run_client, _prompt_registry(), MODEL, cache_dir=tmp_path
    )

    assert len(second_run_client.requests) == 1  # only the uncached second batch
    assert len(contexts) == CONTEXTUALIZE_BATCH_SIZE + 1
