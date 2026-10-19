from fin_ai_lab.core.evals.graders._util import get_field, require_expected_field
from fin_ai_lab.core.evals.models import Case, GradeResult, GraderSpec, RunContext


class ClassificationMetricsGrader:
    """Per-case correctness for one categorical field, recording expected
    and actual in `details` so a caller (P4-S7's comparison report) can
    later aggregate the pairs into a real macro-F1 and confusion matrix —
    the runner's own metrics (`_compute_metrics` in runner.py) only ever
    averages a per-case score, which is not the same number as macro-F1
    under class imbalance.

    `name` is set per instance from `field`, unlike `ExactGrader.name`
    (a fixed class attribute) — two `exact` graders on different fields in
    the same suite would collide on the same `grader:exact` metrics key.
    That's a pre-existing gap in `exact`/`numeric`, out of scope here; this
    grader needs two independent fields (sentiment, event_type) in the same
    suite, so it avoids the collision instead of inheriting it.
    """

    def __init__(self, spec: GraderSpec) -> None:
        self._field = spec.field
        self.name = f"classification:{spec.field}"

    async def grade(self, case: Case, output: object, ctx: RunContext) -> GradeResult:
        expected = require_expected_field(case, self._field, self.name)
        actual = get_field(output, self._field)
        passed = expected == actual
        return GradeResult(
            score=1.0 if passed else 0.0,
            passed=passed,
            details={"expected": expected, "actual": actual},
        )
