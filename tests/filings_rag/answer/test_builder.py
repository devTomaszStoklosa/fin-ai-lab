from pathlib import Path

import pytest

from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag.answer.builder import build_answer
from fin_ai_lab.filings_rag.answer.verify import AnswerRejectedError
from fin_ai_lab.filings_rag.models import Chunk, RetrievalResult, RetrievedChunk

PROMPTS_DIR = Path("src/fin_ai_lab/filings_rag/prompts")


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


def _chunk() -> Chunk:
    return Chunk(
        id="c1",
        company="Microsoft",
        filing_type="10-K",
        fiscal_period="FY2025",
        section="ITEM 1A. RISK FACTORS",
        text="Our business faces many risks including competition and regulation.",
        source_location="https://example.test/filing.htm",
        language="en",
    )


def _retrieval(top_score: float = 0.9, company_in_corpus: bool = True) -> RetrievalResult:
    return RetrievalResult(
        chunks=[RetrievedChunk(chunk=_chunk(), score=top_score)],
        top_score=top_score,
        company_in_corpus=company_in_corpus,
    )


async def test_build_answer_refuses_when_company_not_in_corpus() -> None:
    llm_client = FakeLlmClient({})  # would KeyError if ever called

    answer = await build_answer(
        "What about Nvidia?",
        _retrieval(company_in_corpus=False),
        llm_client,
        _prompt_registry(),
        "gemini-3.6-flash",
    )

    assert answer.refused is True
    assert answer.refusal_reason == "company_not_in_corpus"
    assert answer.citations == []


async def test_build_answer_refuses_when_top_score_is_below_threshold() -> None:
    llm_client = FakeLlmClient({})  # would KeyError if ever called

    answer = await build_answer(
        "Unrelated question",
        _retrieval(top_score=0.1),
        llm_client,
        _prompt_registry(),
        "gemini-3.6-flash",
        refusal_threshold=0.5,
    )

    assert answer.refused is True
    assert answer.refusal_reason == "no_relevant_chunk"


async def test_build_answer_returns_a_faithful_answer_with_citations() -> None:
    draft = (
        '{"text": "There is competition risk.", "citations": [{"company": "Microsoft", '
        '"filing_type": "10-K", "fiscal_period": "FY2025", "section": "ITEM 1A. RISK FACTORS", '
        '"excerpt": "risks including competition and regulation"}]}'
    )
    llm_client = FakeLlmClient({"answer": draft})

    answer = await build_answer(
        "What competition risk does Microsoft face?",
        _retrieval(),
        llm_client,
        _prompt_registry(),
        "gemini-3.6-flash",
    )

    assert answer.refused is False
    assert answer.text == "There is competition risk."
    assert len(answer.citations) == 1


async def test_build_answer_rejects_a_fabricated_citation() -> None:
    draft = (
        '{"text": "There is a cybersecurity risk.", "citations": [{"company": "Microsoft", '
        '"filing_type": "10-K", "fiscal_period": "FY2025", "section": "ITEM 1A. RISK FACTORS", '
        '"excerpt": "a massive cybersecurity breach occurred"}]}'
    )
    llm_client = FakeLlmClient({"answer": draft})

    with pytest.raises(AnswerRejectedError):
        await build_answer(
            "Any cybersecurity risk?",
            _retrieval(),
            llm_client,
            _prompt_registry(),
            "gemini-3.6-flash",
        )
