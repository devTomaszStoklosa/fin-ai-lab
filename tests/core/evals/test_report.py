from datetime import UTC, datetime

from fin_ai_lab.core.evals.models import CaseResult, GradeResult, GraderSpec, RunSummary, Suite
from fin_ai_lab.core.evals.report import render_report

_NOW = datetime.now(UTC)


def _suite() -> Suite:
    return Suite(
        name="demo",
        dataset_version=1,
        target="fin_ai_lab.core.evals.smoke_target:target",
        graders=[GraderSpec(type="numeric", field="sum")],
    )


def test_render_report_without_baseline_suggests_save_baseline() -> None:
    summary = RunSummary(
        suite="demo",
        dataset_version=1,
        started_at=_NOW,
        finished_at=_NOW,
        case_count=1,
        metrics={"grader:numeric": {"pass_rate": 1.0, "avg_score": 1.0, "n": 1.0}},
    )
    case_results = [
        CaseResult(
            case_id="c1",
            split="dev",
            repeat_index=0,
            passed=True,
            grades={"numeric": GradeResult(score=1.0, passed=True)},
        )
    ]

    report = render_report(_suite(), summary, case_results, baseline=None)

    assert "--save-baseline" in report


def test_render_report_lists_regressions_against_baseline() -> None:
    summary = RunSummary(
        suite="demo",
        dataset_version=1,
        started_at=_NOW,
        finished_at=_NOW,
        case_count=1,
        metrics={"grader:numeric": {"pass_rate": 0.0, "avg_score": 0.0, "n": 1.0}},
    )
    case_results = [
        CaseResult(
            case_id="c1",
            split="dev",
            repeat_index=0,
            passed=False,
            grades={"numeric": GradeResult(score=0.0, passed=False)},
        )
    ]
    baseline = {
        "dataset_version": 1,
        "metrics": {"grader:numeric": {"pass_rate": 1.0, "avg_score": 1.0, "n": 1.0}},
        "cases": {"c1": True},
    }

    report = render_report(_suite(), summary, case_results, baseline)

    assert "c1" in report.split("### Regresje")[1]


def test_render_report_skips_delta_when_dataset_version_differs() -> None:
    summary = RunSummary(
        suite="demo", dataset_version=2, started_at=_NOW, finished_at=_NOW, case_count=0
    )
    baseline = {"dataset_version": 1, "metrics": {}, "cases": {}}

    report = render_report(_suite(), summary, [], baseline)

    assert "różni się" in report
    assert "### Regresje" not in report
