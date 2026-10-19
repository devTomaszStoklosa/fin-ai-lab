"""P2's public surface for other projects (docs/ARCHITECTURE.md rule 6) —
today the web app's "Zapytaj raport" tab (#225). Reads the index saved by
`filings-rag build-index` (#253); never builds or extends it."""

from pathlib import Path

from pydantic import BaseModel

from fin_ai_lab.core.llm.client import LlmClient
from fin_ai_lab.core.llm.embeddings import EmbeddingClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.filings_rag.answer.builder import build_answer
from fin_ai_lab.filings_rag.answer.verify import AnswerRejectedError
from fin_ai_lab.filings_rag.index.persist import INDEX_PATH, SavedIndex, load_index
from fin_ai_lab.filings_rag.models import Answer, Citation, FilingType, Language, RefusalReason
from fin_ai_lab.filings_rag.retrieval.hybrid import DEFAULT_TOP_K, retrieve_hybrid

__all__ = [
    "INDEX_PATH",
    "PROMPTS_DIR",
    "Answer",
    "AnswerRejectedError",
    "Citation",
    "IndexedCompany",
    "RefusalReason",
    "SavedIndex",
    "SavedIndexCache",
    "UnknownCompanyError",
    "ask",
    "indexed_companies",
]

PROMPTS_DIR = Path("src/fin_ai_lab/filings_rag/prompts")


class UnknownCompanyError(Exception):
    def __init__(self, company: str) -> None:
        super().__init__(f"Company not in the saved index: {company}")
        self.company = company


class IndexedCompany(BaseModel):
    company: str
    filing_type: FilingType
    fiscal_period: str
    language: Language
    sections: list[str]
    chunk_count: int


class SavedIndexCache:
    """Loads the saved index once and again only after the file changes —
    a rebuild from the CLI shows up in an already running web app without
    a restart, and an unchanged index isn't re-read on every request."""

    def __init__(self, path: Path = INDEX_PATH) -> None:
        self._path = path
        self._mtime_ns: int | None = None
        self._index: SavedIndex | None = None

    def get(self) -> SavedIndex | None:
        try:
            mtime_ns = self._path.stat().st_mtime_ns
        except FileNotFoundError:
            self._mtime_ns = None
            self._index = None
            return None

        if mtime_ns != self._mtime_ns:
            self._index = load_index(self._path)
            self._mtime_ns = mtime_ns
        return self._index


def indexed_companies(index: SavedIndex) -> list[IndexedCompany]:
    # The corpus holds one filing per company (corpus.py), so a company's
    # filing type and period are those of its first chunk.
    companies: dict[str, IndexedCompany] = {}
    for chunk in index.store.chunks:
        entry = companies.get(chunk.company)
        if entry is None:
            companies[chunk.company] = IndexedCompany(
                company=chunk.company,
                filing_type=chunk.filing_type,
                fiscal_period=chunk.fiscal_period,
                language=chunk.language,
                sections=[chunk.section],
                chunk_count=1,
            )
            continue
        entry.chunk_count += 1
        if chunk.section not in entry.sections:
            entry.sections.append(chunk.section)
    return list(companies.values())


async def ask(
    question: str,
    index: SavedIndex,
    *,
    company: str | None,
    llm_client: LlmClient,
    embedding_client: EmbeddingClient,
    prompt_registry: PromptRegistry,
    model: str,
) -> Answer:
    """One embedding call for the question and one generate call for the
    answer (#225's cost budget) — no LLM reranker, unlike the eval pipeline
    (qa_target), which would double the Gemini calls per question.

    With `company`, the search covers only that company's chunks and the
    question doesn't have to name it. Without it, the existing rule
    applies: a question that names no indexed company is refused as
    company_not_in_corpus."""
    if company is not None and not index.store.has_company(company):
        raise UnknownCompanyError(company)

    known_companies = (
        None if company is not None else [entry.company for entry in indexed_companies(index)]
    )
    retrieval = await retrieve_hybrid(
        question,
        index.store,
        embedding_client=embedding_client,
        embedding_model=index.embedding_model,
        known_companies=known_companies,
        top_k=DEFAULT_TOP_K,
        company=company,
    )
    return await build_answer(question, retrieval, llm_client, prompt_registry, model)
