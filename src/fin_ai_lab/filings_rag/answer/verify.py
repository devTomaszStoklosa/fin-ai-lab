import re

from fin_ai_lab.filings_rag.models import Answer, Chunk, Citation

_WHITESPACE_RE = re.compile(r"\s+")


class AnswerRejectedError(Exception):
    def __init__(self, mismatches: list[str]) -> None:
        super().__init__(f"Answer rejected, citations not faithful to chunks: {mismatches}")
        self.mismatches = mismatches


def verify_citations_faithful(answer: Answer, chunks_by_id: dict[str, Chunk]) -> list[str]:
    """REQ-020, the citation-side analog of P1-S5's verify_numbers_faithful:
    every citation's excerpt must be a real (whitespace-normalized)
    substring of some chunk matching its metadata — never a paraphrase or a
    fabrication."""
    chunks = list(chunks_by_id.values())
    mismatches: list[str] = []
    for citation in answer.citations:
        if not _excerpt_found(citation, chunks):
            mismatches.append(citation.excerpt)
    return mismatches


def _excerpt_found(citation: Citation, chunks: list[Chunk]) -> bool:
    normalized_excerpt = _normalize(citation.excerpt)
    if not normalized_excerpt:
        return False
    for chunk in chunks:
        if (
            chunk.company == citation.company
            and chunk.filing_type == citation.filing_type
            and chunk.fiscal_period == citation.fiscal_period
            and chunk.section == citation.section
            and normalized_excerpt in _normalize(chunk.text)
        ):
            return True
    return False


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip().lower()
