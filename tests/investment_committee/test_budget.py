from decimal import Decimal

from fin_ai_lab.investment_committee.budget import BudgetGuard


def test_check_allows_spending_within_budget() -> None:
    guard = BudgetGuard(budget_usd=Decimal("1.00"), max_iterations=10)

    assert guard.check(Decimal("0.30")) is True


def test_check_rejects_spending_that_would_exceed_budget() -> None:
    guard = BudgetGuard(budget_usd=Decimal("1.00"), max_iterations=10)
    guard.record(Decimal("0.80"))

    assert guard.check(Decimal("0.30")) is False


def test_check_rejects_once_max_iterations_reached_even_with_budget_left() -> None:
    guard = BudgetGuard(budget_usd=Decimal("10.00"), max_iterations=2)
    guard.record(Decimal("0.01"))
    guard.record(Decimal("0.01"))

    assert guard.check(Decimal("0.01")) is False


def test_record_accumulates_spend_and_iterations() -> None:
    guard = BudgetGuard(budget_usd=Decimal("1.00"), max_iterations=10)

    guard.record(Decimal("0.25"))
    guard.record(Decimal("0.25"))

    assert guard.spent_usd == Decimal("0.50")
    assert guard.iterations == 2
