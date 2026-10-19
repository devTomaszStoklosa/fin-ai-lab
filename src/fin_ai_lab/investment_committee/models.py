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
    # ASSUMPTION (03-design.md's contract sketch omits both — added because
    # REQ-011 is unimplementable without them): `perspective` groups theses
    # for the per-perspective Brier score REQ-011 asks for; `confidence` is
    # the predicted probability of "accurate" a Brier score needs as input.
    perspective: Perspective
    confidence: float
    outcome: ThesisOutcome | None = None


class CommitteeReport(BaseModel):
    portfolio_id: str
    date: date
    briefs: list[Brief] = []
    disagreements: list[str] = []
    reckoning: list[Thesis] = []
    text: str
    cost_usd: Decimal = Decimal(0)


class VariantResult(BaseModel):
    text: str
    cost_usd: Decimal
    latency_ms: int


class ComparisonReport(BaseModel):
    portfolio_id: str
    single_agent: VariantResult
    committee: VariantResult
    quality_winner: Literal["single_agent", "committee", "tie"]
    quality_reason: str
