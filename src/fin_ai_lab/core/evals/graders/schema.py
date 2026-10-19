from fin_ai_lab.core.errors import GraderError
from fin_ai_lab.core.evals._imports import import_ref
from fin_ai_lab.core.evals.models import Case, GradeResult, GraderSpec, RunContext


class SchemaGrader:
    name = "schema"

    def __init__(self, spec: GraderSpec) -> None:
        schema_ref = spec.params.get("schema")
        if not schema_ref:
            raise GraderError("Grader 'schema' needs params.schema")
        self._schema = import_ref(schema_ref, GraderError, label="Schema")

    async def grade(self, case: Case, output: object, ctx: RunContext) -> GradeResult:
        try:
            self._schema.model_validate(output)
        except Exception as exc:
            return GradeResult(score=0.0, passed=False, details={"error": str(exc)})
        return GradeResult(score=1.0, passed=True, details={})
