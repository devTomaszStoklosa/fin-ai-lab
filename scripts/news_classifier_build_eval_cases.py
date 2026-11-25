"""P4-S7: builds the shared golden test set for the p4-classifier-*
suites from the human-reviewed calibration CSV (REQ-011's review, reused
as ground truth).

Default: rebuilds the current version, the headlines pinned in
`src/fin_ai_lab/news_classifier/golden_test_set.json` (issue #9). The
corpus keeps growing, so recomputing the set from today's split would give
a different (usually empty) one.

`--new-version`: picks a new set — the corpus's chronological test split
intersected with the reviewed CSV (REQ-022 forbids evaluating on data any
compared model saw during training/few-shot, so only the test split
qualifies) — and pins it as the next version. Bump `dataset_version` in
the five suite.yaml files to match afterwards.

`core/evals`'s loader always reads `<suite_dir>/cases.jsonl` (no shared-
cases mechanism across suites) — rather than change that shared contract
for one project, this script writes identical copies into every
p4-classifier-* suite directory, so they stay in sync mechanically.

The cases are real press headlines, so the written files are gitignored;
version 1 of the set stays in git history (docs/EVALS.md, "Dane
licencjonowane").

Run from the repo root: `uv run python scripts/news_classifier_build_eval_cases.py`.
"""

import argparse
import json
from pathlib import Path

from fin_ai_lab.news_classifier.corpus_store import load_labeled
from fin_ai_lab.news_classifier.golden_test_set import (
    load_golden_test_set,
    pin_golden_test_set,
    save_golden_test_set,
    select_golden_test_items,
)
from fin_ai_lab.news_classifier.labeling.review import build_golden_set
from fin_ai_lab.news_classifier.models import LabeledHeadline
from fin_ai_lab.news_classifier.split import split_chronological

REVIEWED_PATH = Path("data/review/news_classifier_review.csv")
SUITE_DIRS = [
    Path("evals/p4-classifier-majority"),
    Path("evals/p4-classifier-tfidf"),
    Path("evals/p4-classifier-few-shot"),
    Path("evals/p4-classifier-herbert"),
    Path("evals/p4-classifier-quantized"),
]


def _case(index: int, item: LabeledHeadline) -> dict:
    return {
        "id": f"p4-classifier-{index:03d}",
        "split": "test",
        "input": {
            "headline": item.headline.headline,
            "lead": item.headline.lead,
            "source": item.headline.source,
            "published_at": item.headline.published_at.isoformat(),
        },
        "expected": {"sentiment": item.label.sentiment, "event_type": item.label.event_type},
        "tags": [],
        "provenance": "human",
    }


def _pick_new_test_items() -> list[LabeledHeadline]:
    corpus = load_labeled()
    _train, _dev, test = split_chronological(corpus)
    test_texts = {item.headline.headline for item in test}

    golden = build_golden_set(REVIEWED_PATH)
    golden_test = [item for item in golden if item.headline.headline in test_texts]
    if not golden_test:
        raise ValueError(
            "No headline is both in the chronological test split and human-reviewed — "
            "nothing to build a golden test set from."
        )
    return golden_test


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build cases.jsonl for the p4-classifier-* eval suites."
    )
    parser.add_argument(
        "--new-version",
        action="store_true",
        help="pick a new set from today's test split and pin it as the next version",
    )
    args = parser.parse_args()

    pinned = load_golden_test_set()
    if args.new_version:
        items = _pick_new_test_items()
        pinned = pin_golden_test_set(items, dataset_version=pinned.dataset_version + 1)
        save_golden_test_set(pinned)
    else:
        items = select_golden_test_items(build_golden_set(REVIEWED_PATH), pinned)

    cases = [_case(i, item) for i, item in enumerate(items, start=1)]
    lines = "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n"
    for suite_dir in SUITE_DIRS:
        suite_dir.mkdir(parents=True, exist_ok=True)
        (suite_dir / "cases.jsonl").write_text(lines, encoding="utf-8")
    print(
        f"Wrote {len(cases)} cases (golden test set version {pinned.dataset_version}) "
        f"to {len(SUITE_DIRS)} suite directories"
    )
    if args.new_version:
        print(
            f"Pinned the new set; set dataset_version: {pinned.dataset_version} "
            "in every p4-classifier-* suite.yaml."
        )


if __name__ == "__main__":
    main()
