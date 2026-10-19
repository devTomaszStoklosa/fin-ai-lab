from datetime import date
from decimal import Decimal
from pathlib import Path

from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.portfolio_xray.canonical import Position
from fin_ai_lab.portfolio_xray.sectors.classifier import category_for_non_equity, classify_sector

PROMPTS_DIR = Path("src/fin_ai_lab/portfolio_xray/sectors/prompts")


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


def _position(**overrides: object) -> Position:
    fields = dict(
        broker="test",
        account_type="regular",
        instrument_name="Apple Inc",
        symbol="AAPL",
        asset_class="equity",
        quantity=Decimal("1"),
        valuation_date=date(2026, 9, 15),
    )
    fields.update(overrides)
    return Position(**fields)


def test_category_for_non_equity_maps_etf_and_fund_to_etf_fund() -> None:
    assert category_for_non_equity("etf") == "ETF/fund"
    assert category_for_non_equity("fund") == "ETF/fund"


def test_category_for_non_equity_passes_through_other_classes() -> None:
    assert category_for_non_equity("bond") == "bond"
    assert category_for_non_equity("crypto") == "crypto"


async def test_classify_sector_skips_llm_for_non_equity() -> None:
    llm_client = FakeLlmClient({})  # would KeyError if ever called
    position = _position(asset_class="bond")

    sector = await classify_sector(position, llm_client, _prompt_registry(), "gemini-2.5-flash")

    assert sector == "bond"
    assert llm_client.requests == []


async def test_classify_sector_returns_model_answer_for_equity() -> None:
    llm_client = FakeLlmClient({"classify_sector": '{"sector": "Technology"}'})

    sector = await classify_sector(
        _position(), llm_client, _prompt_registry(), "gemini-2.5-flash"
    )

    assert sector == "Technology"


async def test_classify_sector_falls_back_to_other_for_unknown_answer() -> None:
    llm_client = FakeLlmClient({"classify_sector": '{"sector": "Not A Real Sector"}'})

    sector = await classify_sector(
        _position(), llm_client, _prompt_registry(), "gemini-2.5-flash"
    )

    assert sector == "other"
