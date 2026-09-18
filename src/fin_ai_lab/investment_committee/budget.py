from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class BudgetGuard:
    """REQ-020/021: two independent hard stops, both checked every call —
    cost alone isn't enough (an agent could loop many times cheaply) and
    an iteration cap alone isn't enough (one call could blow the budget)."""

    budget_usd: Decimal
    max_iterations: int
    spent_usd: Decimal = field(default=Decimal(0), init=False)
    iterations: int = field(default=0, init=False)

    def check(self, estimated_additional_cost: Decimal) -> bool:
        if self.iterations >= self.max_iterations:
            return False
        return self.spent_usd + estimated_additional_cost <= self.budget_usd

    def record(self, actual_cost: Decimal) -> None:
        self.spent_usd += actual_cost
        self.iterations += 1
