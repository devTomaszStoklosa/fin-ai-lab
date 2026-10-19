from decimal import Decimal

from fin_ai_lab.core.llm.pricing import PRICES


def test_flash_lite_cost_is_flat_regardless_of_input_size() -> None:
    price = PRICES["gemini-2.5-flash-lite"]

    cost = price.cost_usd(input_tokens=1_000_000, output_tokens=1_000_000)

    assert cost == Decimal("0.10") + Decimal("0.40")


def test_pro_cost_uses_lower_tier_at_or_under_threshold() -> None:
    price = PRICES["gemini-2.5-pro"]

    cost = price.cost_usd(input_tokens=200_000, output_tokens=0)

    assert cost == Decimal("1.25") * 200_000 / 1_000_000


def test_pro_cost_uses_higher_tier_above_threshold() -> None:
    price = PRICES["gemini-2.5-pro"]

    cost = price.cost_usd(input_tokens=200_001, output_tokens=0)

    assert cost == Decimal("2.50") * 200_001 / 1_000_000
