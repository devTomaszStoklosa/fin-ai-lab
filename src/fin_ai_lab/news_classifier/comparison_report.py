import json
from pathlib import Path
from typing import TypedDict, get_args

from fin_ai_lab.news_classifier.metrics import confusion_matrix, macro_f1, per_class_metrics
from fin_ai_lab.news_classifier.models import EventType, Sentiment

SENTIMENTS = list(get_args(Sentiment))
EVENT_TYPES = list(get_args(EventType))

RUNS_DIR = Path("evals/runs")

# P4-S7 (REQ-020): one row per compared model, same order every time.
SUITES = {
    "majority": "p4-classifier-majority",
    "tfidf": "p4-classifier-tfidf",
    "few-shot": "p4-classifier-few-shot",
    "herbert": "p4-classifier-herbert",
    "quantized": "p4-classifier-quantized",
}


class ModelReport(TypedDict):
    model: str
    n_cases: int
    sentiment_macro_f1: float
    event_type_macro_f1: float
    cost_per_1000_usd: float
    latency_p50_ms: float
    latency_p95_ms: float
    sentiment_per_class: dict
    event_type_per_class: dict
    sentiment_confusion: dict
    event_type_confusion: dict


def _latest_run_dir(suite_name: str, runs_dir: Path) -> Path:
    candidates = sorted(
        d for d in runs_dir.iterdir() if d.is_dir() and d.name.endswith(f"-{suite_name}")
    )
    if not candidates:
        raise ValueError(
            f"No eval run found for suite '{suite_name}' in {runs_dir} — run "
            f"'fin-ai-lab eval {suite_name} --split test' first."
        )
    return candidates[-1]


def _pairs_for_field(run_dir: Path, field: str) -> list[tuple[str, str]]:
    grader_key = f"classification:{field}"
    pairs: list[tuple[str, str]] = []
    for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        result = json.loads(line)
        grade = result["grades"].get(grader_key)
        if grade is None:
            continue
        pairs.append((grade["details"]["expected"], grade["details"]["actual"]))
    return pairs


def build_model_report(model: str, runs_dir: Path = RUNS_DIR) -> ModelReport:
    suite_name = SUITES[model]
    run_dir = _latest_run_dir(suite_name, runs_dir)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))

    sentiment_pairs = _pairs_for_field(run_dir, "sentiment")
    event_type_pairs = _pairs_for_field(run_dir, "event_type")
    n_cases = summary["case_count"]

    return ModelReport(
        model=model,
        n_cases=n_cases,
        sentiment_macro_f1=macro_f1(sentiment_pairs, SENTIMENTS),
        event_type_macro_f1=macro_f1(event_type_pairs, EVENT_TYPES),
        cost_per_1000_usd=float(summary["cost_usd"]) / n_cases * 1000 if n_cases else 0.0,
        latency_p50_ms=summary["latency_p50_ms"],
        latency_p95_ms=summary["latency_p95_ms"],
        sentiment_per_class=per_class_metrics(sentiment_pairs, SENTIMENTS),
        event_type_per_class=per_class_metrics(event_type_pairs, EVENT_TYPES),
        sentiment_confusion=confusion_matrix(sentiment_pairs, SENTIMENTS),
        event_type_confusion=confusion_matrix(event_type_pairs, EVENT_TYPES),
    )


def render_comparison_report(reports: list[ModelReport]) -> str:
    lines = [
        "# P4-S7: raport porównawczy — baseline'y vs HerBERT",
        "",
        "REQ-020: macro-F1 (sentiment, event type), koszt/1000 nagłówków, latencja p50/p95, "
        "na tym samym zbiorze testowym (chronologiczny test-split ∩ human-reviewed, REQ-022 — "
        "żaden model nie widział tych nagłówków w treningu/few-shot).",
        "",
        "## Podsumowanie",
        "",
        "| Model | n | sentiment macro-F1 | event_type macro-F1 | koszt/1000 (USD) | "
        "latency p50 (ms) | latency p95 (ms) |",
        "|---|---|---|---|---|---|---|",
    ]
    for report in reports:
        lines.append(
            f"| {report['model']} | {report['n_cases']} | "
            f"{report['sentiment_macro_f1']:.3f} | {report['event_type_macro_f1']:.3f} | "
            f"{report['cost_per_1000_usd']:.4f} | {report['latency_p50_ms']:.1f} | "
            f"{report['latency_p95_ms']:.1f} |"
        )

    lines += ["", "## Klasy bez wsparcia w zbiorze testowym", ""]
    lines.append(
        "REQ-020 edge case: rzadkie typy zdarzeń zgłoszone tu, nie ukryte uśrednieniem "
        "(docs/EVALS.md zasada 5) — macro-F1 powyżej liczy się tylko po klasach z support > 0."
    )
    for report in reports:
        zero_support = [
            label
            for label, metrics in report["event_type_per_class"].items()
            if metrics["support"] == 0
        ]
        if zero_support:
            lines.append(f"- **{report['model']}**: brak przykładów dla: {', '.join(zero_support)}")

    return "\n".join(lines) + "\n"
