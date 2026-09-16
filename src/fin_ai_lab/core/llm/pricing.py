from datetime import date
from decimal import Decimal

from pydantic import BaseModel

PRICES_AS_OF = date(2026, 9, 16)

MILLION = Decimal(1_000_000)


class PriceTier(BaseModel):
    up_to_input_tokens: int | None
    input_price_per_million: Decimal
    output_price_per_million: Decimal


class ModelPrice(BaseModel):
    tiers: list[PriceTier]

    def tier_for(self, input_tokens: int) -> PriceTier:
        for tier in self.tiers:
            if tier.up_to_input_tokens is None or input_tokens <= tier.up_to_input_tokens:
                return tier
        return self.tiers[-1]

    def cost_usd(self, input_tokens: int, output_tokens: int) -> Decimal:
        tier = self.tier_for(input_tokens)
        input_cost = tier.input_price_per_million * input_tokens / MILLION
        output_cost = tier.output_price_per_million * output_tokens / MILLION
        return input_cost + output_cost


PRICES: dict[str, ModelPrice] = {
    "gemini-2.5-pro": ModelPrice(
        tiers=[
            PriceTier(
                up_to_input_tokens=200_000,
                input_price_per_million=Decimal("1.25"),
                output_price_per_million=Decimal("10.00"),
            ),
            PriceTier(
                up_to_input_tokens=None,
                input_price_per_million=Decimal("2.50"),
                output_price_per_million=Decimal("15.00"),
            ),
        ]
    ),
    "gemini-2.5-flash": ModelPrice(
        tiers=[
            PriceTier(
                up_to_input_tokens=None,
                input_price_per_million=Decimal("0.30"),
                output_price_per_million=Decimal("2.50"),
            ),
        ]
    ),
    "gemini-2.5-flash-lite": ModelPrice(
        tiers=[
            PriceTier(
                up_to_input_tokens=None,
                input_price_per_million=Decimal("0.10"),
                output_price_per_million=Decimal("0.40"),
            ),
        ]
    ),
    # gemini-2.5-flash returns 404 for new API keys ("no longer available to
    # new users"); ai.google.dev/gemini-api/docs/pricing points to this as
    # the replacement. Price valid through 2026-12-31 (rises after).
    "gemini-3.6-flash": ModelPrice(
        tiers=[
            PriceTier(
                up_to_input_tokens=None,
                input_price_per_million=Decimal("0.75"),
                output_price_per_million=Decimal("3.75"),
            ),
        ]
    ),
}
