from fin_ai_lab.core.evals.graders.classification_metrics import ClassificationMetricsGrader
from fin_ai_lab.core.evals.models import Case, GraderSpec


def _case(expected: dict | None) -> Case:
    return Case(id="c1", input={}, expected=expected, provenance="synthetic")


async def test_classification_metrics_passes_on_equal_values() -> None:
    grader = ClassificationMetricsGrader(
        GraderSpec(type="classification_metrics", field="sentiment")
    )
    case = _case({"sentiment": "positive"})

    result = await grader.grade(case, {"sentiment": "positive"}, ctx=None)

    assert result.passed is True
    assert result.score == 1.0
    assert result.details == {"expected": "positive", "actual": "positive"}


async def test_classification_metrics_fails_on_different_values() -> None:
    grader = ClassificationMetricsGrader(
        GraderSpec(type="classification_metrics", field="sentiment")
    )
    case = _case({"sentiment": "positive"})

    result = await grader.grade(case, {"sentiment": "negative"}, ctx=None)

    assert result.passed is False
    assert result.details == {"expected": "positive", "actual": "negative"}


async def test_classification_metrics_name_is_scoped_to_its_field() -> None:
    sentiment_grader = ClassificationMetricsGrader(
        GraderSpec(type="classification_metrics", field="sentiment")
    )
    event_type_grader = ClassificationMetricsGrader(
        GraderSpec(type="classification_metrics", field="event_type")
    )

    assert sentiment_grader.name == "classification:sentiment"
    assert event_type_grader.name == "classification:event_type"
    assert sentiment_grader.name != event_type_grader.name
