"""Issue #9: the P4 golden test set, pinned by identity.

The set used to be recomputed each time as "the corpus's chronological
test split intersected with the human-reviewed CSV". The labeling task
keeps appending headlines to the corpus, so that split keeps moving to
newer, never-reviewed headlines, and the set could no longer be rebuilt.

`golden_test_set.json` (committed) lists which headlines make up the
current set, in case order, as SHA-256 fingerprints of their normalized
text: enough to rebuild the exact same `cases.jsonl` from the reviewed CSV
without putting press headlines into the repo (docs/EVALS.md, "Dane
licencjonowane")."""

import hashlib
from pathlib import Path

from pydantic import BaseModel

from fin_ai_lab.news_classifier.models import LabeledHeadline
from fin_ai_lab.news_classifier.split import normalize_headline_text

GOLDEN_TEST_SET_PATH = Path(__file__).with_name("golden_test_set.json")


class GoldenTestSet(BaseModel):
    # Same number as `dataset_version` in the p4-classifier-* suite.yaml files.
    dataset_version: int
    headline_sha256: list[str]


def headline_fingerprint(text: str) -> str:
    # Normalized the same way split.py removes near-duplicates, so a
    # re-published copy of a test headline gets the same fingerprint.
    return hashlib.sha256(normalize_headline_text(text).encode("utf-8")).hexdigest()


def load_golden_test_set(path: Path = GOLDEN_TEST_SET_PATH) -> GoldenTestSet:
    return GoldenTestSet.model_validate_json(path.read_text(encoding="utf-8"))


def save_golden_test_set(test_set: GoldenTestSet, path: Path = GOLDEN_TEST_SET_PATH) -> None:
    path.write_text(test_set.model_dump_json(indent=2) + "\n", encoding="utf-8")


def pin_golden_test_set(items: list[LabeledHeadline], dataset_version: int) -> GoldenTestSet:
    return GoldenTestSet(
        dataset_version=dataset_version,
        headline_sha256=[headline_fingerprint(item.headline.headline) for item in items],
    )


def select_golden_test_items(
    reviewed: list[LabeledHeadline], test_set: GoldenTestSet
) -> list[LabeledHeadline]:
    """The reviewed items the pinned set names, in the pinned order. Fails
    instead of returning a smaller set when the reviewed CSV no longer has
    one of them: a silently shrunk set would still look like version N."""
    by_fingerprint: dict[str, LabeledHeadline] = {}
    for item in reviewed:
        by_fingerprint.setdefault(headline_fingerprint(item.headline.headline), item)

    missing = [digest for digest in test_set.headline_sha256 if digest not in by_fingerprint]
    if missing:
        raise ValueError(
            f"The reviewed CSV has no row for {len(missing)} of the "
            f"{len(test_set.headline_sha256)} headlines pinned in golden test set "
            f"version {test_set.dataset_version}."
        )
    return [by_fingerprint[digest] for digest in test_set.headline_sha256]
