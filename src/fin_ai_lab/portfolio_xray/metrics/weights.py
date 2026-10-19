from decimal import Decimal

from pydantic import BaseModel

from fin_ai_lab.portfolio_xray.canonical import Position

TOP_N_SHARE = 5


class WeightedPosition(BaseModel):
    position: Position
    weight: Decimal
    base_currency_value: Decimal


class WeightMetrics(BaseModel):
    weighted_positions: list[WeightedPosition]
    allocation_by_asset_class: dict[str, Decimal]
    allocation_by_currency: dict[str, Decimal]
    allocation_by_account_type: dict[str, Decimal]
    hhi: Decimal
    effective_positions: Decimal
    top5_share: Decimal


def compute_weights(positions_with_base_value: list[tuple[Position, Decimal]]) -> WeightMetrics:
    total = sum((value for _, value in positions_with_base_value), Decimal(0))
    if total <= 0:
        raise ValueError("Portfolio has no positive total value")

    weighted = [
        WeightedPosition(position=position, weight=value / total, base_currency_value=value)
        for position, value in positions_with_base_value
    ]

    hhi = sum((w.weight * w.weight for w in weighted), Decimal(0))
    effective_positions = (Decimal(1) / hhi) if hhi > 0 else Decimal(0)
    top5_share = sum(
        (w.weight for w in sorted(weighted, key=lambda w: w.weight, reverse=True)[:TOP_N_SHARE]),
        Decimal(0),
    )

    return WeightMetrics(
        weighted_positions=weighted,
        allocation_by_asset_class=_allocation_by(weighted, lambda w: w.position.asset_class),
        allocation_by_currency=_allocation_by(
            weighted, lambda w: w.position.market_currency or "unknown"
        ),
        allocation_by_account_type=_allocation_by(weighted, lambda w: w.position.account_type),
        hhi=hhi,
        effective_positions=effective_positions,
        top5_share=top5_share,
    )


def _allocation_by(weighted: list[WeightedPosition], key) -> dict[str, Decimal]:
    allocation: dict[str, Decimal] = {}
    for entry in weighted:
        bucket = key(entry)
        allocation[bucket] = allocation.get(bucket, Decimal(0)) + entry.weight
    return allocation
