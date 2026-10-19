from datetime import date
from decimal import Decimal

import pytest

pytest.importorskip("duckdb")

from fin_ai_lab.portfolio_webapp.investment_result import (  # noqa: E402
    CashFlow,
    investment_result,
)
from fin_ai_lab.portfolio_webapp.valuation import MissingFxRateError  # noqa: E402

D = Decimal


def test_result_is_proceeds_plus_open_value_minus_cost() -> None:
    outcome = investment_result(
        purchases=[
            CashFlow(date(2026, 1, 1), "PLN", D("1000")),
            CashFlow(date(2026, 1, 2), "PLN", D("500")),
        ],
        sales=[CashFlow(date(2026, 1, 3), "PLN", D("300"))],
        open_value=D("1400"),
        fx_rates={},
    )

    assert outcome.invested == D("1500")
    assert outcome.proceeds == D("300")
    assert outcome.result == D("200")


def test_each_flow_uses_the_rate_of_its_own_day() -> None:
    rates = {"USD": {date(2026, 1, 1): D("4.00"), date(2026, 1, 5): D("4.50")}}

    outcome = investment_result(
        purchases=[CashFlow(date(2026, 1, 1), "USD", D("100"))],
        sales=[CashFlow(date(2026, 1, 6), "USD", D("10"))],  # weekend-style gap: last rate wins
        open_value=D("0"),
        fx_rates=rates,
    )

    assert outcome.invested == D("400.00")
    assert outcome.proceeds == D("45.00")


def test_net_deposits_are_deposits_minus_withdrawals_and_never_change_the_result() -> None:
    rates = {"USD": {date(2026, 1, 1): D("4.00"), date(2026, 1, 5): D("4.50")}}
    deposits = [
        CashFlow(date(2026, 1, 1), "USD", D("1000")),
        CashFlow(date(2026, 1, 5), "USD", D("-200")),  # a withdrawal
    ]

    with_deposits = investment_result(
        purchases=[CashFlow(date(2026, 1, 1), "USD", D("100"))],
        sales=[],
        open_value=D("500"),
        fx_rates=rates,
        deposits=deposits,
    )
    without = investment_result(
        purchases=[CashFlow(date(2026, 1, 1), "USD", D("100"))],
        sales=[],
        open_value=D("500"),
        fx_rates=rates,
    )

    assert with_deposits.net_deposits == D("3100.00")  # 1000 x 4.00 - 200 x 4.50
    assert without.net_deposits is None
    assert with_deposits.result == without.result == D("100")


def test_a_loss_is_negative() -> None:
    outcome = investment_result(
        purchases=[CashFlow(date(2026, 1, 1), "PLN", D("1000"))],
        sales=[],
        open_value=D("900"),
        fx_rates={},
    )

    assert outcome.result == D("-100")


def test_currency_without_rates_is_reported_not_guessed() -> None:
    with pytest.raises(MissingFxRateError) as raised:
        investment_result(
            purchases=[CashFlow(date(2026, 1, 1), "USD", D("100"))],
            sales=[],
            open_value=D("0"),
            fx_rates={},
        )

    assert raised.value.currency == "USD"
