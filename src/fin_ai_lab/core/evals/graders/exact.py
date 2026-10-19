from fin_ai_lab.core.evals.graders._util import get_field, require_expected_field
from fin_ai_lab.core.evals.models import Case, GradeResult, GraderSpec, RunContext


class ExactGrader:
    name = "exact"

    def __init__(self, spec: GraderSpec) -> None:
        self._field = spec.field
        self._case_insensitive = bool(spec.params.get("case_insensitive", False))
        self._strip_whitespace = bool(spec.params.get("strip_whitespace", True))

    async def grade(self, case: Case, output: object, ctx: RunContext) -> GradeResult:
        expected = require_expected_field(case, self._field, self.name)
        actual = get_field(output, self._field)
        passed = self._normalize(expected) == self._normalize(actual)
        return GradeResult(
            score=1.0 if passed else 0.0,
            passed=passed,
            details={"expected": expected, "actual": actual},
        )

    def _normalize(self, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip() if self._strip_whitespace else value
            return normalized.lower() if self._case_insensitive else normalized
        return value
