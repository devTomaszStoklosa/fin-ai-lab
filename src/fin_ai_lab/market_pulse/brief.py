import asyncio
import json
from datetime import date

from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.market_pulse.models import Brief, IndicatorObservation, NewsItem, RegimeResult

NO_US_DATA_TEXT = "Brak danych o wskaźnikach USA w tym przebiegu."
NO_PL_DATA_TEXT = "Brak danych o wskaźnikach PL w tym przebiegu."
NO_NEWS_TEXT = "Brak newsów w tym przebiegu."


async def build_brief(
    indicators: list[IndicatorObservation],
    regime: RegimeResult,
    missing_sources: list[str],
    news: list[NewsItem],
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
) -> Brief:
    """P3-S4: orchestrator-workers (docs/LEARNING.md glossary) — this
    function is the orchestrator. It splits the brief into independent
    domains (US macro, PL FX/rates, PL news), dispatches one LLM worker
    call per domain in parallel, and assembles the final text in code.
    The regime line itself is written entirely in code, from the
    already-computed RegimeResult — never restated or re-derived by a
    worker (CLAUDE.md rule 2, REQ-010/011)."""
    us_indicators = [observation for observation in indicators if observation.source == "fred"]
    pl_indicators = [
        observation for observation in indicators if observation.source in ("nbp-fx", "nbp-rate")
    ]

    us_text, pl_text, news_text = await asyncio.gather(
        _write_indicators_section(
            llm_client, prompt_registry, model, "brief_us", us_indicators, NO_US_DATA_TEXT
        ),
        _write_indicators_section(
            llm_client, prompt_registry, model, "brief_pl", pl_indicators, NO_PL_DATA_TEXT
        ),
        _write_news_section(llm_client, prompt_registry, model, news),
    )

    signals = "; ".join(regime.signals) if regime.signals else "brak sygnałów progowych"
    header = f"Reżim rynku: {regime.regime}. Sygnały, które o tym zdecydowały: {signals}."
    missing_line = (
        f"Źródła niedostępne w tym przebiegu: {', '.join(missing_sources)}."
        if missing_sources
        else None
    )
    text = "\n\n".join(
        part for part in [header, us_text, pl_text, news_text, missing_line] if part
    )

    return Brief(
        date=date.today(),
        regime=regime.regime,
        regime_rationale=regime.signals,
        indicators=indicators,
        missing_sources=missing_sources,
        text=text,
    )


async def _write_indicators_section(
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    prompt_id: str,
    indicators: list[IndicatorObservation],
    empty_text: str,
) -> str:
    if not indicators:
        return empty_text

    prompt = prompt_registry.get(prompt_id, 1)
    payload = json.dumps(_indicators_payload(indicators), ensure_ascii=False)
    rendered = prompt.render(indicators_json=payload)
    request = LlmRequest(
        model=model, messages=[{"role": "user", "text": rendered}],
        prompt_id=prompt_id, prompt_version=1,
    )
    result = await llm_client.complete(request)
    return result.text


async def _write_news_section(
    llm_client: LlmClient, prompt_registry: PromptRegistry, model: str, news: list[NewsItem]
) -> str:
    if not news:
        return NO_NEWS_TEXT

    prompt = prompt_registry.get("brief_news", 1)
    rendered = prompt.render(news_json=json.dumps(_news_payload(news), ensure_ascii=False))
    request = LlmRequest(
        model=model, messages=[{"role": "user", "text": rendered}],
        prompt_id="brief_news", prompt_version=1,
    )
    result = await llm_client.complete(request)
    return result.text


def _indicators_payload(indicators: list[IndicatorObservation]) -> list[dict]:
    return [
        {
            "series_id": observation.series_id,
            "label": observation.label,
            "value": str(observation.value),
            "unit": observation.unit,
            "as_of_date": observation.as_of_date.isoformat(),
        }
        for observation in indicators
    ]


def _news_payload(news: list[NewsItem]) -> list[dict]:
    return [{"title": item.title, "summary": item.summary, "source": item.source} for item in news]
