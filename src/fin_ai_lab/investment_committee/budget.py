from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class BudgetGuard:
    """REQ-020/021: two independent hard stops, both checked every call —
    cost alone isn't enough (an agent could loop many times cheaply) and
    an iteration cap alone isn't enough (one call could blow the budget).

    P5-S6: `on_budget_exceeded` is the human-in-the-loop hook REQ-020
    asks for ("najpierw prosi o akceptację" — ask before stopping, don't
    just stop). Left unset (as every pre-S6 caller does), a hit stop
    stays a silent, fail-safe deny — the same behavior as before this
    slice. `01-story.md`'s open question #3 answered: the CLI wires this
    to an interactive `typer.confirm`, one prompt per run — once approved,
    the run continues unchecked rather than re-prompting on every call."""

    budget_usd: Decimal
    max_iterations: int
    on_budget_exceeded: Callable[[], bool] | None = None
    spent_usd: Decimal = field(default=Decimal(0), init=False)
    iterations: int = field(default=0, init=False)
    _approved_override: bool = field(default=False, init=False)

    def check(self, estimated_additional_cost: Decimal) -> bool:
        if self._approved_override:
            return True
        within_limits = (
            self.iterations < self.max_iterations
            and self.spent_usd + estimated_additional_cost <= self.budget_usd
        )
        if within_limits:
            return True
        if self.on_budget_exceeded is None:
            return False
        self._approved_override = self.on_budget_exceeded()
        return self._approved_override

    def record(self, actual_cost: Decimal) -> None:
        self.spent_usd += actual_cost
        self.iterations += 1
