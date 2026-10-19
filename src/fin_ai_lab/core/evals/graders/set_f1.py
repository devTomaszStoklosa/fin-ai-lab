from fin_ai_lab.core.evals.graders._util import get_field, require_expected_field, to_hashable
from fin_ai_lab.core.evals.models import Case, GradeResult, GraderSpec, RunContext


class SetF1Grader:
    name = "set_f1"

    def __init__(self, spec: GraderSpec) -> None:
        self._field = spec.field

    async def grade(self, case: Case, output: object, ctx: RunContext) -> GradeResult:
        expected_raw = require_expected_field(case, self._field, self.name)
        actual_raw = get_field(output, self._field) or []

        expected_set = {to_hashable(item) for item in expected_raw}
        actual_set = {to_hashable(item) for item in actual_raw}

        true_positives = len(expected_set & actual_set)
        precision = true_positives / len(actual_set) if actual_set else 0.0
        recall = true_positives / len(expected_set) if expected_set else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        return GradeResult(
            score=f1,
            passed=f1 == 1.0,
            details={"precision": precision, "recall": recall, "f1": f1},
        )
