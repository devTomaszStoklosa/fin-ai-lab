from fin_ai_lab.core.evals.graders.set_f1 import SetF1Grader
from fin_ai_lab.core.evals.models import Case, GraderSpec


def _case(expected: list) -> Case:
    return Case(id="c1", input={}, expected={"tickers": expected}, provenance="synthetic")


async def test_set_f1_perfect_match_scores_one() -> None:
    grader = SetF1Grader(GraderSpec(type="set_f1", field="tickers"))
    case = _case(["AAA", "BBB"])

    result = await grader.grade(case, {"tickers": ["AAA", "BBB"]}, ctx=None)

    assert result.score == 1.0
    assert result.passed is True


async def test_set_f1_partial_overlap_scores_between_zero_and_one() -> None:
    grader = SetF1Grader(GraderSpec(type="set_f1", field="tickers"))
    case = _case(["AAA", "BBB"])

    result = await grader.grade(case, {"tickers": ["AAA", "CCC"]}, ctx=None)

    assert 0.0 < result.score < 1.0
    assert result.passed is False
