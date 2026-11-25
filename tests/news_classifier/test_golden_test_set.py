from datetime import UTC, datetime
from pathlib import Path

import pytest

from fin_ai_lab.news_classifier.golden_test_set import (
    GOLDEN_TEST_SET_PATH,
    GoldenTestSet,
    headline_fingerprint,
    load_golden_test_set,
    pin_golden_test_set,
    save_golden_test_set,
    select_golden_test_items,
)
from fin_ai_lab.news_classifier.models import Headline, Label, LabeledHeadline


def _item(text: str) -> LabeledHeadline:
    return LabeledHeadline(
        headline=Headline(
            headline=text, source="test", published_at=datetime(2026, 1, 1, tzinfo=UTC)
        ),
        label=Label(sentiment="neutral", event_type="inne", tickers=[]),
        source_model="human",
    )


def test_fingerprint_ignores_case_and_whitespace_like_the_split_dedup() -> None:
    assert headline_fingerprint("Orlen  podał wyniki ") == headline_fingerprint(
        "orlen podał wyniki"
    )
    assert headline_fingerprint("Orlen podał wyniki") != headline_fingerprint("PZU podał wyniki")


def test_select_returns_pinned_items_in_pinned_order() -> None:
    first, second, other = _item("Pierwszy"), _item("Drugi"), _item("Inny")
    pinned = pin_golden_test_set([second, first], dataset_version=1)

    selected = select_golden_test_items([first, other, second], pinned)

    assert [item.headline.headline for item in selected] == ["Drugi", "Pierwszy"]


def test_select_fails_when_a_pinned_headline_is_missing() -> None:
    pinned = pin_golden_test_set([_item("Pierwszy"), _item("Drugi")], dataset_version=3)

    with pytest.raises(
        ValueError, match="no row for 1 of the 2 headlines pinned in golden test set version 3"
    ):
        select_golden_test_items([_item("Pierwszy")], pinned)


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "set.json"
    pinned = GoldenTestSet(dataset_version=2, headline_sha256=["a" * 64])

    save_golden_test_set(pinned, path)

    assert load_golden_test_set(path) == pinned


def test_committed_set_matches_the_p4_suites_dataset_version() -> None:
    # The pinned set and the suites' dataset_version must move together
    # (docs/EVALS.md: a new set is a new dataset_version and a new baseline).
    import yaml

    pinned = load_golden_test_set(GOLDEN_TEST_SET_PATH)
    suite_dirs = sorted(Path("evals").glob("p4-classifier-*"))

    assert suite_dirs
    for suite_dir in suite_dirs:
        suite = yaml.safe_load((suite_dir / "suite.yaml").read_text(encoding="utf-8"))
        assert suite["dataset_version"] == pinned.dataset_version, suite_dir.name
    assert len(pinned.headline_sha256) == len(set(pinned.headline_sha256))
