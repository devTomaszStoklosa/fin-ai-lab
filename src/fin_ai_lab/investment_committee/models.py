from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

Perspective = Literal["fundamental", "macro", "sentiment", "stress"]
SourceType = Literal["tool_result", "filing_excerpt", "computed_metric"]
ThesisOutcome = Literal["accurate", "inaccurate", "not_yet_resolvable"]


class Claim(BaseModel):
    text: str
    source_type: SourceType
    source_ref: str


class Brief(BaseModel):
    perspective: Perspective
    conclusion: str
    confidence: float
    claims: list[Claim] = []


class StressScenario(BaseModel):
    name: str
    shock: dict[str, Decimal]
    portfolio_impact: Decimal


class Thesis(BaseModel):
    statement: str
    made_at: date
    horizon: str
    outcome: ThesisOutcome | None = None


class CommitteeReport(BaseModel):
    portfolio_id: str
    date: date
    briefs: list[Brief] = []
    disagreements: list[str] = []
    reckoning: list[Thesis] = []
    text: str
    cost_usd: Decimal = Decimal(0)
