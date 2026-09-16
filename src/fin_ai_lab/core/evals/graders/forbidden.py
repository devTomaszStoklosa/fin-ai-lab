import re

from fin_ai_lab.core.errors import GraderError
from fin_ai_lab.core.evals.graders._util import get_field
from fin_ai_lab.core.evals.models import Case, GradeResult, GraderSpec, RunContext


class ForbiddenGrader:
    name = "forbidden"

    def __init__(self, spec: GraderSpec) -> None:
        phrases = spec.params.get("phrases")
        if not phrases:
            raise GraderError("Grader 'forbidden' needs params.phrases")
        # Word-boundary match, not a raw substring: a plain "phrase in text"
        # check flags e.g. "kup" inside "kupna", including inside a sentence
        # that denies being a recommendation ("nie jest sugestią kupna...").
        self._patterns = [
            (phrase, re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE))
            for phrase in phrases
        ]
        self._field = spec.field

    async def grade(self, case: Case, output: object, ctx: RunContext) -> GradeResult:
        text = str(get_field(output, self._field) or "")
        found = [phrase for phrase, pattern in self._patterns if pattern.search(text)]
        passed = not found
        return GradeResult(score=1.0 if passed else 0.0, passed=passed, details={"found": found})
