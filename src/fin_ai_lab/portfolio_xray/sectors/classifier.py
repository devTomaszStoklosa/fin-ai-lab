from pydantic import BaseModel

from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.portfolio_xray.canonical import Position

# REQ-030a: GICS-like sectors for equity; everything else gets its asset
# class as the category instead of a sector — an ETF or bond doesn't have
# "a sector" the way a single company does.
GICS_LIKE_SECTORS = [
    "Technology",
    "Financials",
    "Industrials",
    "Healthcare",
    "Energy",
    "Materials",
    "Consumer",
    "Real Estate",
    "Utilities",
    "Communication",
]


class SectorClassification(BaseModel):
    sector: str


def category_for_non_equity(asset_class: str) -> str:
    if asset_class in ("etf", "fund"):
        return "ETF/fund"
    return asset_class


async def classify_sector(
    position: Position,
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
) -> str:
    if position.asset_class != "equity":
        return category_for_non_equity(position.asset_class)

    prompt = prompt_registry.get("classify_sector", 1)
    rendered = prompt.render(
        instrument_name=position.instrument_name,
        symbol=position.symbol or "",
        sectors=", ".join(GICS_LIKE_SECTORS),
    )
    request = LlmRequest(
        model=model,
        messages=[{"role": "user", "text": rendered}],
        response_schema=SectorClassification,
        prompt_id="classify_sector",
        prompt_version=1,
    )
    result = await llm_client.complete(request)
    if not isinstance(result.parsed, SectorClassification):
        return "other"

    return result.parsed.sector if result.parsed.sector in GICS_LIKE_SECTORS else "other"
