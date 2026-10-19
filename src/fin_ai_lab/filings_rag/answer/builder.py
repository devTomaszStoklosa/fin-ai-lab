import json

from pydantic import BaseModel

from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag.answer.verify import AnswerRejectedError, verify_citations_faithful
from fin_ai_lab.filings_rag.models import Answer, Citation, RefusalReason, RetrievalResult
from fin_ai_lab.filings_rag.retrieval.naive import DEFAULT_REFUSAL_THRESHOLD

_REFUSAL_TEXT = {
    "company_not_in_corpus": "Nie mam danych dla tej spółki w zaindeksowanym korpusie.",
    "no_relevant_chunk": "Nie znalazłem odpowiedzi w zaindeksowanych dokumentach.",
}


class _CitationDraft(BaseModel):
    company: str
    filing_type: str
    fiscal_period: str
    section: str
    excerpt: str


class _AnswerDraft(BaseModel):
    text: str
    citations: list[_CitationDraft]


async def build_answer(
    query: str,
    retrieval: RetrievalResult,
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    *,
    refusal_threshold: float = DEFAULT_REFUSAL_THRESHOLD,
) -> Answer:
    if not retrieval.company_in_corpus:
        return _refusal("company_not_in_corpus")
    if not retrieval.chunks or retrieval.top_score < refusal_threshold:
        return _refusal("no_relevant_chunk")

    payload = _chunks_payload(retrieval)
    prompt = prompt_registry.get("answer", 1)
    rendered = prompt.render(question=query, chunks_json=json.dumps(payload, ensure_ascii=False))

    request = LlmRequest(
        model=model,
        messages=[{"role": "user", "text": rendered}],
        response_schema=_AnswerDraft,
        prompt_id="answer",
        prompt_version=1,
    )
    result = await llm_client.complete(request)
    draft = result.parsed
    if not isinstance(draft, _AnswerDraft):
        return _refusal("no_relevant_chunk")

    answer = Answer(
        text=draft.text,
        citations=[Citation(**citation.model_dump()) for citation in draft.citations],
        refused=False,
    )

    chunks_by_id = {retrieved.chunk.id: retrieved.chunk for retrieved in retrieval.chunks}
    mismatches = verify_citations_faithful(answer, chunks_by_id)
    if mismatches:
        raise AnswerRejectedError(mismatches)
    return answer


def _refusal(reason: RefusalReason) -> Answer:
    return Answer(text=_REFUSAL_TEXT[reason], citations=[], refused=True, refusal_reason=reason)


def _chunks_payload(retrieval: RetrievalResult) -> list[dict]:
    return [
        {
            "company": retrieved.chunk.company,
            "filing_type": retrieved.chunk.filing_type,
            "fiscal_period": retrieved.chunk.fiscal_period,
            "section": retrieved.chunk.section,
            "text": retrieved.chunk.text,
        }
        for retrieved in retrieval.chunks
    ]
