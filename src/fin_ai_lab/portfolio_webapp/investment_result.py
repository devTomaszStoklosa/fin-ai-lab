"""Investment result of one portfolio (fin-ai-lab#238, #241) -- pure
computation, every amount a Decimal in PLN.

Result = proceeds of sales + current value of open positions - cost of every
purchase + what the account earned on the side (dividends after withholding
tax, interest on free funds, fees and other small adjustments). Each cash flow
is converted with the NBP rate of its own day, so a currency move between
buying and now is part of the result, as it is in the owner's pocket.
Deposits and withdrawals never enter the result: the question is how much the
purchases are worth more (or less) than they cost, not how much cash went
through the account. Their net sum is reported next to it as `net_deposits`,
the money the owner actually put in -- the base for a percentage.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fin_ai_lab.portfolio_webapp.valuation import base_rate_lookup


@dataclass(frozen=True)
class CashFlow:
    """One purchase, sale, side income or transfer, in its own currency.
    Purchases and sales carry a positive amount; side income and transfers
    are signed (a fee or a withdrawal is negative)."""

    on: date
    currency: str
    amount: Decimal


@dataclass(frozen=True)
class InvestmentResult:
    invested: Decimal  # cost of every purchase
    proceeds: Decimal  # money taken out by sales
    open_value: Decimal  # what the open positions are worth now
    dividends: Decimal = Decimal(0)  # net of withholding tax
    interest: Decimal = Decimal(0)  # on free funds, net of its tax
    other: Decimal = Decimal(0)  # fees, swaps, corrections
    # Deposits minus withdrawals; None when the import has no deposit data.
    net_deposits: Decimal | None = None

    @property
    def result(self) -> Decimal:
        return (
            self.proceeds
            + self.open_value
            - self.invested
            + self.dividends
            + self.interest
            + self.other
        )


def investment_result(
    purchases: list[CashFlow],
    sales: list[CashFlow],
    open_value: Decimal,
    fx_rates: dict[str, dict[date, Decimal]],
    *,
    dividends: list[CashFlow] | None = None,
    interest: list[CashFlow] | None = None,
    other: list[CashFlow] | None = None,
    deposits: list[CashFlow] | None = None,
) -> InvestmentResult:
    """`open_value` is already in PLN. Raises MissingFxRateError when a flow's
    currency has no rate series -- the caller then reports no result rather
    than a wrong one."""
    lookups: dict[str, Callable[[date], Decimal]] = {}

    def total(flows: list[CashFlow] | None) -> Decimal:
        amount = Decimal(0)
        for flow in flows or []:
            if flow.currency not in lookups:
                lookups[flow.currency] = base_rate_lookup(flow.currency, fx_rates)
            amount += flow.amount * lookups[flow.currency](flow.on)
        return amount

    return InvestmentResult(
        invested=total(purchases),
        proceeds=total(sales),
        open_value=open_value,
        dividends=total(dividends),
        interest=total(interest),
        other=total(other),
        net_deposits=total(deposits) if deposits else None,
    )
