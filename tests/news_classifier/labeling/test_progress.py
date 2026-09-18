from datetime import datetime

from fin_ai_lab.news_classifier.labeling.progress import (
    headline_key,
    load_labeled_keys,
    save_labeled_keys,
    unlabeled,
)
from fin_ai_lab.news_classifier.models import Headline


def _headline(text: str) -> Headline:
    return Headline(
        headline=text, source="bankier", published_at=datetime(2026, 9, 17, 12, 0, 0)
    )


def test_save_and_load_round_trip(tmp_path) -> None:
    path = tmp_path / "labeled.json"
    keys = {headline_key(_headline("a")), headline_key(_headline("b"))}

    save_labeled_keys(keys, path=path)

    assert load_labeled_keys(path=path) == keys


def test_load_with_no_file_returns_empty_set(tmp_path) -> None:
    assert load_labeled_keys(path=tmp_path / "missing.json") == set()


def test_unlabeled_filters_out_already_labeled_headlines() -> None:
    a, b = _headline("a"), _headline("b")
    already_labeled = {headline_key(a)}

    result = unlabeled([a, b], already_labeled)

    assert result == [b]
