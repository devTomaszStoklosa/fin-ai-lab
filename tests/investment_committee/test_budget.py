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


def test_check_asks_for_approval_when_budget_exceeded_and_hook_is_set() -> None:
    asked = []
    guard = BudgetGuard(
        budget_usd=Decimal("1.00"), max_iterations=10,
        on_budget_exceeded=lambda: asked.append(1) or True,
    )
    guard.record(Decimal("0.80"))

    assert guard.check(Decimal("0.30")) is True
    assert asked == [1]


def test_check_denies_when_the_approval_hook_declines() -> None:
    guard = BudgetGuard(
        budget_usd=Decimal("1.00"), max_iterations=10, on_budget_exceeded=lambda: False
    )
    guard.record(Decimal("0.80"))

    assert guard.check(Decimal("0.30")) is False


def test_check_only_asks_once_then_stays_approved_for_the_rest_of_the_run() -> None:
    calls = []
    guard = BudgetGuard(
        budget_usd=Decimal("1.00"), max_iterations=10,
        on_budget_exceeded=lambda: calls.append(1) or True,
    )
    guard.record(Decimal("0.80"))

    assert guard.check(Decimal("0.30")) is True
    assert guard.check(Decimal("5.00")) is True  # way over budget, but already approved
    assert len(calls) == 1


def test_check_without_a_hook_still_denies_exactly_as_before_s6() -> None:
    guard = BudgetGuard(budget_usd=Decimal("1.00"), max_iterations=10)
    guard.record(Decimal("0.80"))

    assert guard.check(Decimal("0.30")) is False
