from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, field_validator

from fin_ai_lab.core.evals.cache import EvalCache
from fin_ai_lab.core.llm.client import LlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry


class GraderSpec(BaseModel):
    type: str
    field: str | None = None
    params: dict = {}


class Case(BaseModel):
    id: str
    split: str = "dev"
    input: dict
    expected: dict | None = None
    tags: list[str] = []
    provenance: str


class Suite(BaseModel):
    name: str
    dataset_version: int
    target: str
    model: str | None = None
    effort: str | None = None
    prompt_versions: dict[str, int] = {}
    graders: list[GraderSpec]
    repeats: int = 1
    concurrency: int = 4
    max_cost_usd: Decimal | None = None

    @field_validator("dataset_version")
    @classmethod
    def _dataset_version_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("dataset_version must be >= 1")
        return value

    @field_validator("graders")
    @classmethod
    def _graders_non_empty(cls, value: list[GraderSpec]) -> list[GraderSpec]:
        if not value:
            raise ValueError("Suite has no graders")
        return value

    @field_validator("repeats")
    @classmethod
    def _repeats_in_range(cls, value: int) -> int:
        if not 1 <= value <= 10:
            raise ValueError("repeats out of range")
        return value

    @field_validator("concurrency")
    @classmethod
    def _concurrency_in_range(cls, value: int) -> int:
        if not 1 <= value <= 16:
            raise ValueError("concurrency out of range")
        return value

    @field_validator("max_cost_usd")
    @classmethod
    def _max_cost_positive(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value <= 0:
            raise ValueError("max_cost_usd must be positive")
        return value


class GradeResult(BaseModel):
    score: float
    passed: bool
    details: dict = {}


class CaseResult(BaseModel):
    case_id: str
    split: str
    repeat_index: int
    tags: list[str] = []
    passed: bool
    grades: dict[str, GradeResult] = {}
    error: str | None = None
    cost_usd: Decimal = Decimal(0)
    latency_ms: int = 0
    cache_hit: bool = False


class RunSummary(BaseModel):
    suite: str
    dataset_version: int
    started_at: datetime
    finished_at: datetime | None = None
    incomplete: bool = False
    model: str | None = None
    effort: str | None = None
    prompt_versions: dict[str, int] = {}
    git_commit: str | None = None
    cost_usd: Decimal = Decimal(0)
    case_count: int = 0
    cache_hits: int = 0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    metrics: dict[str, dict[str, float]] = {}
    # Case id -> passed, for the last executed repeat; with repeats > 1 the
    # regression list below is only approximate (later repeats overwrite earlier ones).
    cases: dict[str, bool] = {}


@dataclass
class RunContext:
    llm_client: LlmClient
    prompts: PromptRegistry
    cache: EvalCache
    model: str | None = None
    effort: str | None = None
