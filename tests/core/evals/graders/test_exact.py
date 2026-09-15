import pytest

from fin_ai_lab.core.errors import GraderError
from fin_ai_lab.core.evals.graders.exact import ExactGrader
from fin_ai_lab.core.evals.models import Case, GraderSpec


def _case(expected: dict | None) -> Case:
    return Case(id="c1", input={}, expected=expected, provenance="synthetic")


async def test_exact_passes_on_equal_values() -> None:
    grader = ExactGrader(GraderSpec(type="exact", field="label"))
    case = _case({"label": "buy"})

    result = await grader.grade(case, {"label": "buy"}, ctx=None)

    assert result.passed is True
    assert result.score == 1.0


async def test_exact_case_insensitive_normalizes_before_comparing() -> None:
    grader = ExactGrader(GraderSpec(type="exact", field="label", params={"case_insensitive": True}))
    case = _case({"label": "Buy"})

    result = await grader.grade(case, {"label": "buy"}, ctx=None)

    assert result.passed is True


async def test_exact_fails_on_different_values() -> None:
    grader = ExactGrader(GraderSpec(type="exact", field="label"))
    case = _case({"label": "buy"})

    result = await grader.grade(case, {"label": "sell"}, ctx=None)

    assert result.passed is False


async def test_exact_raises_when_expected_field_missing() -> None:
    grader = ExactGrader(GraderSpec(type="exact", field="label"))
    case = _case(None)

    with pytest.raises(GraderError):
        await grader.grade(case, {"label": "buy"}, ctx=None)
