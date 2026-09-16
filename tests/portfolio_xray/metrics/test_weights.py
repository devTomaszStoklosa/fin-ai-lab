from datetime import date
from decimal import Decimal

import pytest

from fin_ai_lab.portfolio_xray.canonical import Position
from fin_ai_lab.portfolio_xray.metrics.weights import compute_weights


def _position(**overrides: object) -> Position:
    fields = dict(
        broker="test",
        account_type="regular",
        instrument_name="Widget Co",
        asset_class="equity",
        quantity=Decimal("1"),
        market_currency="PLN",
        valuation_date=date(2026, 9, 15),
    )
    fields.update(overrides)
    return Position(**fields)


def test_weights_sum_to_one() -> None:
    positions = [
        (_position(), Decimal("60")),
        (_position(asset_class="etf"), Decimal("40")),
    ]

    metrics = compute_weights(positions)

    assert sum(w.weight for w in metrics.weighted_positions) == Decimal(1)


def test_hhi_and_effective_positions_for_equal_weights() -> None:
    positions = [(_position(), Decimal("25")) for _ in range(4)]

    metrics = compute_weights(positions)

    assert metrics.hhi == Decimal("0.25")
    assert metrics.effective_positions == Decimal(4)


def test_top5_share_caps_at_five_largest() -> None:
    positions = [(_position(), Decimal(value)) for value in [50, 20, 10, 10, 5, 5]]

    metrics = compute_weights(positions)

    assert metrics.top5_share == Decimal("95") / Decimal("100")


def test_allocation_by_asset_class_groups_correctly() -> None:
    positions = [
        (_position(asset_class="equity"), Decimal("70")),
        (_position(asset_class="etf"), Decimal("30")),
    ]

    metrics = compute_weights(positions)

    assert metrics.allocation_by_asset_class["equity"] == Decimal("70") / Decimal("100")
    assert metrics.allocation_by_asset_class["etf"] == Decimal("30") / Decimal("100")


def test_zero_total_value_raises() -> None:
    with pytest.raises(ValueError, match="no positive total value"):
        compute_weights([(_position(), Decimal(0))])
