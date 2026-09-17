from pathlib import Path

from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag.models import Chunk
from fin_ai_lab.filings_rag.retrieval.contextual import contextualize

PROMPTS_DIR = Path("src/fin_ai_lab/filings_rag/prompts")
MODEL = "gemini-3.6-flash"


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


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
