import json
from pathlib import Path

import pytest

from fin_ai_lab.news_classifier.comparison_report import (
    build_model_report,
    render_comparison_report,
)


def _write_run(runs_dir: Path, suite_name: str, run_id: str, pairs: dict, cost_usd: str) -> None:
    run_dir = runs_dir / f"20260919T000000-aaaa-{suite_name}"
    run_dir.mkdir(parents=True)
    results = []
    for i, (sentiment_expected, sentiment_actual, event_expected, event_actual) in enumerate(
        pairs, start=1
    ):
        results.append(
            {
                "case_id": f"case-{i}",
                "split": "test",
                "repeat_index": 0,
                "tags": [],
                "passed": sentiment_expected == sentiment_actual,
                "grades": {
                    "classification:sentiment": {
                        "score": 1.0 if sentiment_expected == sentiment_actual else 0.0,
                        "passed": sentiment_expected == sentiment_actual,
                        "details": {"expected": sentiment_expected, "actual": sentiment_actual},
                    },
                    "classification:event_type": {
                        "score": 1.0 if event_expected == event_actual else 0.0,
                        "passed": event_expected == event_actual,
                        "details": {"expected": event_expected, "actual": event_actual},
                    },
                },
                "error": None,
                "cost_usd": "0",
                "latency_ms": 10,
                "cache_hit": False,
            }
        )
    (run_dir / "results.jsonl").write_text(
        "\n".join(json.dumps(r) for r in results) + "\n", encoding="utf-8"
    )
    summary = {
        "suite": suite_name,
        "dataset_version": 1,
        "started_at": "2026-09-19T00:00:00Z",
        "case_count": len(results),
        "cost_usd": cost_usd,
        "latency_p50_ms": 12.0,
        "latency_p95_ms": 20.0,
        "cache_hits": 0,
        "cases": {},
        "metrics": {},
    }
    (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


def test_build_model_report_computes_macro_f1_from_results(tmp_path: Path) -> None:
    _write_run(
        tmp_path,
        "p4-classifier-majority",
        "run1",
        pairs=[
            ("positive", "neutral", "wyniki finansowe", "inne"),
            ("neutral", "neutral", "inne", "inne"),
        ],
        cost_usd="0",
    )

    report = build_model_report("majority", runs_dir=tmp_path)

    assert report["n_cases"] == 2
    assert report["cost_per_1000_usd"] == 0.0
    assert 0.0 <= report["sentiment_macro_f1"] <= 1.0


def test_build_model_report_raises_when_no_run_exists(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="No eval run found"):
        build_model_report("majority", runs_dir=tmp_path)


def test_render_comparison_report_lists_zero_support_classes(tmp_path: Path) -> None:
    _write_run(
        tmp_path,
        "p4-classifier-majority",
        "run1",
        pairs=[("neutral", "neutral", "inne", "inne")],
        cost_usd="0",
    )
    report = build_model_report("majority", runs_dir=tmp_path)

    text = render_comparison_report([report])

    assert "majority" in text
    assert "brak przykładów dla" in text
