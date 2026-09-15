from decimal import Decimal

from fin_ai_lab.core.evals.graders._util import get_field, require_expected_field
from fin_ai_lab.core.evals.models import Case, GradeResult, GraderSpec, RunContext


class NumericGrader:
    name = "numeric"

    def __init__(self, spec: GraderSpec) -> None:
        self._field = spec.field
        self._abs_tol = spec.params.get("abs_tol")
        self._rel_tol = spec.params.get("rel_tol")

    async def grade(self, case: Case, output: object, ctx: RunContext) -> GradeResult:
        expected_raw = require_expected_field(case, self._field, self.name)
        expected = Decimal(str(expected_raw))

        actual_raw = get_field(output, self._field)
        if actual_raw is None:
            return GradeResult(
                score=0.0, passed=False, details={"expected": str(expected), "actual": None}
            )
        actual = Decimal(str(actual_raw))

        diff = abs(expected - actual)
        tolerance = Decimal(str(self._abs_tol)) if self._abs_tol is not None else Decimal(0)
        if self._rel_tol is not None:
            tolerance = max(tolerance, abs(expected) * Decimal(str(self._rel_tol)))

        passed = diff <= tolerance
        return GradeResult(
            score=1.0 if passed else 0.0,
            passed=passed,
            details={"expected": str(expected), "actual": str(actual), "diff": str(diff)},
        )
