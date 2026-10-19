from pydantic import BaseModel

from fin_ai_lab.core.errors import GraderError
from fin_ai_lab.core.evals.cache import cache_key
from fin_ai_lab.core.evals.graders._util import get_field
from fin_ai_lab.core.evals.models import Case, GradeResult, GraderSpec, RunContext
from fin_ai_lab.core.llm.client import LlmRequest


class JudgeVerdict(BaseModel):
    score: float
    passed: bool
    reason: str


class LlmJudgeGrader:
    name = "llm_judge"

    def __init__(self, spec: GraderSpec) -> None:
        rubric = spec.params.get("rubric")
        model = spec.params.get("model")
        if not rubric:
            raise GraderError("Grader 'llm_judge' needs params.rubric")
        if not model:
            raise GraderError("Grader 'llm_judge' needs params.model")
        self._rubric = rubric
        self._model = model
        self._field = spec.field

    async def grade(self, case: Case, output: object, ctx: RunContext) -> GradeResult:
        text = str(get_field(output, self._field))

        key = cache_key({"rubric": self._rubric, "model": self._model, "text": text})
        cached = ctx.cache.get("judge", key)
        if cached is not None:
            return GradeResult(**cached)

        request = LlmRequest(
            model=self._model,
            system_instruction=self._rubric,
            messages=[{"role": "user", "text": text}],
            response_schema=JudgeVerdict,
            prompt_id="llm_judge",
        )
        result = await ctx.llm_client.complete(request)
        verdict = result.parsed
        if not isinstance(verdict, JudgeVerdict):
            raise GraderError(f"Judge for case '{case.id}' returned no parsed verdict")

        grade = GradeResult(
            score=verdict.score, passed=verdict.passed, details={"reason": verdict.reason}
        )
        ctx.cache.set("judge", key, grade.model_dump())
        return grade
