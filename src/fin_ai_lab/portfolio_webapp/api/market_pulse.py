"""Market Pulse endpoints: latest brief, indicators and the ask-a-question tool."""

from datetime import date as date_type
from pathlib import Path

from fastapi import APIRouter, Request
from google.genai import errors as genai_errors

from fin_ai_lab.market_pulse.service import ask as run_market_pulse_ask
from fin_ai_lab.market_pulse.service import classify_regime
from fin_ai_lab.market_pulse.service import load_previous as load_market_pulse_state
from fin_ai_lab.portfolio_webapp.api.common import llm_unavailable
from fin_ai_lab.portfolio_webapp.api.defaults import MODEL
from fin_ai_lab.portfolio_webapp.api.deps import AppDeps
from fin_ai_lab.portfolio_webapp.schemas import (
    MarketPulseAskOut,
    MarketPulseAskRequest,
    MarketPulseBriefOut,
    MarketPulseIndicatorsOut,
)


def _latest_brief_file(briefs_dir: Path) -> tuple[date_type, Path] | None:
    if not briefs_dir.exists():
        return None
    dated_files = []
    for path in briefs_dir.glob("*.md"):
        try:
            brief_date = date_type.fromisoformat(path.stem)
        except ValueError:
            continue
        dated_files.append((brief_date, path))
    if not dated_files:
        return None
    return max(dated_files, key=lambda item: item[0])


def build_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/api/market-pulse/brief/latest", response_model=MarketPulseBriefOut | None)
    def market_pulse_latest_brief() -> MarketPulseBriefOut | None:
        latest = _latest_brief_file(deps.briefs_dir)
        if latest is None:
            return None
        brief_date, path = latest
        return MarketPulseBriefOut(date=brief_date, text=path.read_text(encoding="utf-8"))

    @router.get("/api/market-pulse/indicators", response_model=MarketPulseIndicatorsOut)
    def market_pulse_indicators() -> MarketPulseIndicatorsOut:
        indicators = load_market_pulse_state(deps.market_pulse_state_path)
        regime = classify_regime(indicators)
        return MarketPulseIndicatorsOut(
            regime=regime.regime, regime_signals=regime.signals, indicators=indicators
        )

    @router.post("/api/market-pulse/ask", response_model=MarketPulseAskOut)
    async def market_pulse_ask(
        payload: MarketPulseAskRequest, request: Request
    ) -> MarketPulseAskOut:
        llm_client = deps.llm_client_factory()
        prompt_registry = request.app.state.prompt_registry
        try:
            answer = await run_market_pulse_ask(
                payload.question,
                llm_client,
                prompt_registry,
                MODEL,
                deps.fred_client_factory(),
                deps.nbp_client_factory(),
            )
        except genai_errors.APIError as exc:
            raise llm_unavailable(exc) from exc
        return MarketPulseAskOut(text=answer.text, tool_calls=answer.tool_calls)

    return router
