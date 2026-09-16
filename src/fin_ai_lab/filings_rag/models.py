from typing import Literal

from pydantic import BaseModel

FilingType = Literal["10-K", "annual-report-pl"]
Language = Literal["en", "pl"]


class Chunk(BaseModel):
    id: str
    company: str
    filing_type: FilingType
    fiscal_period: str
    section: str
    text: str
    source_location: str
    language: Language
