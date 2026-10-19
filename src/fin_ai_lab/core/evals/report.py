from fin_ai_lab.core.evals.models import CaseResult, RunSummary, Suite

_WORST_CASES_LIMIT = 5


def render_report(
    suite: Suite,
    summary: RunSummary,
    case_results: list[CaseResult],
    baseline: dict | None,
) -> str:
    lines = [
        f"# Eval report: {suite.name}",
        "",
        f"- dataset_version: {summary.dataset_version}",
        f"- model: {summary.model or '-'}",
        f"- effort: {summary.effort or '-'}",
        f"- git_commit: {summary.git_commit or '-'}",
        f"- started_at: {summary.started_at.isoformat()}",
        f"- finished_at: {summary.finished_at.isoformat() if summary.finished_at else '-'}",
        f"- incomplete: {summary.incomplete}",
        "",
        "## Metrics",
        "",
    ]
    lines += _render_metrics(summary.metrics)

    lines += [
        "",
        "## Cost and latency",
        "",
        f"- cost_usd: {summary.cost_usd}",
        f"- cache_hits: {summary.cache_hits} / {summary.case_count}",
        f"- latency_p50_ms: {summary.latency_p50_ms:.1f}",
        f"- latency_p95_ms: {summary.latency_p95_ms:.1f}",
        "",
    ]

    if baseline is None:
        lines += [
            "## Baseline",
            "",
            "Brak baseline. Uruchom z `--save-baseline`, żeby go zapisać.",
            "",
        ]
    elif baseline.get("dataset_version") != summary.dataset_version:
        lines += [
            "## Baseline",
            "",
            f"dataset_version baseline'u ({baseline.get('dataset_version')}) różni się od "
            f"tego przebiegu ({summary.dataset_version}) — delty pominięte.",
            "",
        ]
    else:
        lines += _render_baseline_delta(summary, baseline, case_results)

    lines += _render_worst_cases(case_results)

    return "\n".join(lines) + "\n"


def _render_metrics(metrics: dict[str, dict[str, float]]) -> list[str]:
    lines = []
    for key in sorted(metrics):
        parts = [f"{name}={value:.3f}" for name, value in metrics[key].items()]
        lines.append(f"- {key}: " + ", ".join(parts))
    return lines


def _render_baseline_delta(
    summary: RunSummary, baseline: dict, case_results: list[CaseResult]
) -> list[str]:
    lines = ["## Baseline delta", ""]

    baseline_metrics: dict[str, dict[str, float]] = baseline.get("metrics", {})
    for key in sorted(summary.metrics):
        previous = baseline_metrics.get(key)
        if previous is None:
            continue
        for metric_name, value in summary.metrics[key].items():
            prev_value = previous.get(metric_name)
            if prev_value is None:
                continue
            delta = value - prev_value
            sign = "+" if delta >= 0 else ""
            lines.append(f"- {key}.{metric_name}: {value:.3f} ({sign}{delta:.3f})")

    baseline_cases: dict[str, bool] = baseline.get("cases", {})
    regressions = sorted(
        {
            result.case_id
            for result in case_results
            if baseline_cases.get(result.case_id) is True and not result.passed
        }
    )

    lines += ["", "### Regresje", ""]
    lines += [f"- {case_id}" for case_id in regressions] if regressions else ["- brak"]
    lines.append("")
    return lines


def _render_worst_cases(case_results: list[CaseResult]) -> list[str]:
    def worst_score(result: CaseResult) -> float:
        if not result.grades:
            return 0.0
        return min(grade.score for grade in result.grades.values())

    worst = sorted(case_results, key=worst_score)[:_WORST_CASES_LIMIT]

    lines = ["## Najgorsze przypadki", ""]
    for result in worst:
        lines.append(
            f"- {result.case_id} (powtórzenie {result.repeat_index}): "
            f"passed={result.passed}, error={result.error or '-'}"
        )
        for name, grade in result.grades.items():
            lines.append(f"  - {name}: score={grade.score:.3f}, details={grade.details}")
    lines.append("")
    return lines
