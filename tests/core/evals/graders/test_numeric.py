from fin_ai_lab.core.evals.graders.numeric import NumericGrader
from fin_ai_lab.core.evals.models import Case, GraderSpec


def _case(expected: dict) -> Case:
    return Case(id="c1", input={}, expected=expected, provenance="synthetic")


async def test_numeric_passes_within_absolute_tolerance() -> None:
    grader = NumericGrader(GraderSpec(type="numeric", field="amount", params={"abs_tol": "0.01"}))
    case = _case({"amount": "10.00"})

    result = await grader.grade(case, {"amount": "10.005"}, ctx=None)

    assert result.passed is True


async def test_numeric_fails_outside_tolerance() -> None:
    grader = NumericGrader(GraderSpec(type="numeric", field="amount"))
    case = _case({"amount": "10"})

    result = await grader.grade(case, {"amount": "11"}, ctx=None)

    assert result.passed is False


async def test_numeric_fails_when_actual_field_missing() -> None:
    grader = NumericGrader(GraderSpec(type="numeric", field="amount"))
    case = _case({"amount": "10"})

    result = await grader.grade(case, {}, ctx=None)

    assert result.passed is False
