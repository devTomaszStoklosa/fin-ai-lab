"""Health and LLM usage endpoints."""

from fastapi import APIRouter

from fin_ai_lab.core.llm.trace import count_calls_today
from fin_ai_lab.portfolio_webapp.api.defaults import KNOWN_FREE_TIER_LIMITS
from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.schemas import LlmUsageOut


def build_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/api/llm-usage", response_model=list[LlmUsageOut])
    def llm_usage() -> list[LlmUsageOut]:
        calls_by_model = count_calls_today(deps.traces_dir)
        return [
            LlmUsageOut(model=model, calls_today=calls_by_model.get(model, 0), rpd_limit=rpd_limit)
            for model, rpd_limit in KNOWN_FREE_TIER_LIMITS.items()
        ]

    return router
