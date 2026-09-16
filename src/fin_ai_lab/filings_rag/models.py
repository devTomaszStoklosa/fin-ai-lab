from typing import Literal

from pydantic import BaseModel

FilingType = Literal["10-K", "annual-report-pl"]
Language = Literal["en", "pl"]
RefusalReason = Literal["no_relevant_chunk", "company_not_in_corpus"]


class Chunk(BaseModel):
    id: str
    company: str
    filing_type: FilingType
    fiscal_period: str
    section: str
    text: str
    source_location: str
    language: Language


class Citation(BaseModel):
    company: str
    filing_type: FilingType
    fiscal_period: str
    section: str
    excerpt: str


class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float


class RetrievalResult(BaseModel):
    chunks: list[RetrievedChunk]
    top_score: float
    company_in_corpus: bool


class Answer(BaseModel):
    text: str
    citations: list[Citation]
    refused: bool
    refusal_reason: RefusalReason | None = None
