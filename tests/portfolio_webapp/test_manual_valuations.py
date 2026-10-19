from datetime import date
from decimal import Decimal

import pytest

from fin_ai_lab.portfolio_webapp.manual_valuations import (
    ManualValuation,
    ValuationDateError,
    current_unit_value,
    market_value,
    validate_purchase_date,
    validate_valuation_date,
)

D = Decimal
TODAY = date(2026, 10, 18)


def test_without_valuations_the_unit_is_worth_its_purchase_price() -> None:
    assert current_unit_value(D(9000), []) == D(9000)
    assert market_value(D(2), D(9000), []) == D(18000)


def test_the_latest_valuation_wins_whatever_the_order() -> None:
    valuations = [
        ManualValuation(valued_on=date(2026, 9, 1), unit_value=D(11000)),
        ManualValuation(valued_on=date(2026, 6, 1), unit_value=D(10000)),
    ]

    assert current_unit_value(D(9000), valuations) == D(11000)
    assert market_value(D(2), D(9000), valuations) == D(22000)


def test_purchase_date_in_the_future_is_refused() -> None:
    with pytest.raises(ValuationDateError, match="przyszłości"):
        validate_purchase_date(date(2026, 10, 19), [], TODAY)


def test_purchase_date_may_not_move_past_the_earliest_valuation() -> None:
    valuations = [ManualValuation(valued_on=date(2026, 6, 1), unit_value=D(10000))]

    validate_purchase_date(date(2026, 6, 1), valuations, TODAY)  # same day is fine
    with pytest.raises(ValuationDateError, match="2026-06-01"):
        validate_purchase_date(date(2026, 6, 2), valuations, TODAY)


def test_valuation_date_must_lie_between_purchase_and_today() -> None:
    validate_valuation_date(date(2026, 3, 10), date(2026, 3, 10), TODAY)
    validate_valuation_date(TODAY, date(2026, 3, 10), TODAY)
    with pytest.raises(ValuationDateError, match="2026-03-10"):
        validate_valuation_date(date(2026, 3, 9), date(2026, 3, 10), TODAY)
    with pytest.raises(ValuationDateError, match="przyszłości"):
        validate_valuation_date(date(2026, 10, 19), date(2026, 3, 10), TODAY)
