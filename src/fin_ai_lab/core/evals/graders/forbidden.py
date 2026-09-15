from fin_ai_lab.core.errors import GraderError
from fin_ai_lab.core.evals.graders._util import get_field
from fin_ai_lab.core.evals.models import Case, GradeResult, GraderSpec, RunContext


class ForbiddenGrader:
    name = "forbidden"

    def __init__(self, spec: GraderSpec) -> None:
        phrases = spec.params.get("phrases")
        if not phrases:
            raise GraderError("Grader 'forbidden' needs params.phrases")
        self._phrases = [phrase.lower() for phrase in phrases]
        self._field = spec.field

    async def grade(self, case: Case, output: object, ctx: RunContext) -> GradeResult:
        text = str(get_field(output, self._field) or "")
        lowered = text.lower()
        found = [phrase for phrase in self._phrases if phrase in lowered]
        passed = not found
        return GradeResult(score=1.0 if passed else 0.0, passed=passed, details={"found": found})
