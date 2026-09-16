from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fin_ai_lab.portfolio_xray.canonical import Position, isin_checksum_is_valid

_TODAY = date(2026, 9, 15)


def _position(**overrides: object) -> Position:
    fields = dict(
        broker="xtb",
        account_type="regular",
        instrument_name="MSCI ACWI",
        asset_class="etf",
        quantity=Decimal("6"),
        avg_cost=Decimal("69.48"),
        cost_currency="PLN",
        market_value=Decimal("2745.41"),
        market_currency="PLN",
        valuation_date=_TODAY,
    )
    fields.update(overrides)
    return Position(**fields)


def test_valid_position_is_accepted() -> None:
    position = _position()

    assert position.resolution_status == "unresolved"


def test_apple_isin_checksum_is_valid() -> None:
    assert isin_checksum_is_valid("US0378331005") is True


def test_flipped_check_digit_is_invalid() -> None:
    assert isin_checksum_is_valid("US0378331004") is False


def test_wrong_length_isin_is_invalid() -> None:
    assert isin_checksum_is_valid("US037833100") is False


def test_new_broker_name_is_accepted() -> None:
    # Not a closed allowlist: P1-S2 onboards new brokers at runtime.
    position = _position(broker="some-new-broker")

    assert position.broker == "some-new-broker"


def test_empty_broker_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown broker"):
        _position(broker="")


def test_zero_quantity_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Quantity must be non-zero"):
        _position(quantity=Decimal(0))


def test_negative_quantity_rejected_for_non_derivative() -> None:
    with pytest.raises(ValidationError, match="Quantity must be non-zero"):
        _position(quantity=Decimal("-1"), asset_class="equity")


def test_negative_quantity_allowed_for_derivative() -> None:
    position = _position(quantity=Decimal("-1"), asset_class="derivative", avg_cost=None,
                          cost_currency=None, market_value=None, market_currency=None)

    assert position.quantity == Decimal("-1")


def test_missing_cost_currency_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown currency"):
        _position(cost_currency=None)


def test_negative_market_value_rejected_for_non_derivative() -> None:
    with pytest.raises(ValidationError, match="Negative market value"):
        _position(market_value=Decimal("-1"))


def test_future_valuation_date_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Valuation date in the future"):
        _position(valuation_date=_TODAY + timedelta(days=1000))


def test_invalid_isin_checksum_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Invalid ISIN checksum"):
        _position(isin="US0378331004")
