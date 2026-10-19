from fin_ai_lab.core.evals.graders.schema import SchemaGrader
from fin_ai_lab.core.evals.models import Case, GraderSpec

_SPEC = GraderSpec(
    type="schema",
    params={"schema": "fin_ai_lab.core.evals.smoke_target:SmokeOutput"},
)


def _case() -> Case:
    return Case(id="c1", input={}, provenance="synthetic")


async def test_schema_passes_for_valid_output() -> None:
    grader = SchemaGrader(_SPEC)

    result = await grader.grade(_case(), {"sum": 5}, ctx=None)

    assert result.passed is True


async def test_schema_fails_for_invalid_output() -> None:
    grader = SchemaGrader(_SPEC)

    result = await grader.grade(_case(), {"sum": "not-a-number"}, ctx=None)

    assert result.passed is False
