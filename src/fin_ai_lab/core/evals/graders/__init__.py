from fin_ai_lab.core.errors import GraderError
from fin_ai_lab.core.evals.graders.exact import ExactGrader
from fin_ai_lab.core.evals.graders.forbidden import ForbiddenGrader
from fin_ai_lab.core.evals.graders.llm_judge import LlmJudgeGrader
from fin_ai_lab.core.evals.graders.numeric import NumericGrader
from fin_ai_lab.core.evals.graders.schema import SchemaGrader
from fin_ai_lab.core.evals.graders.set_f1 import SetF1Grader
from fin_ai_lab.core.evals.models import GraderSpec

_GRADER_TYPES = {
    "exact": ExactGrader,
    "numeric": NumericGrader,
    "schema": SchemaGrader,
    "set_f1": SetF1Grader,
    "forbidden": ForbiddenGrader,
    "llm_judge": LlmJudgeGrader,
}


def build_grader(spec: GraderSpec):
    grader_cls = _GRADER_TYPES.get(spec.type)
    if grader_cls is None:
        raise GraderError(f"Unknown grader type '{spec.type}'")
    return grader_cls(spec)
