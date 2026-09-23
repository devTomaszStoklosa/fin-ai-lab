from datetime import datetime

from fin_ai_lab.news_classifier.labeling.progress import (
    dedupe_pending_by_text,
    headline_key,
    load_labeled_keys,
    save_labeled_keys,
    unlabeled,
)
from fin_ai_lab.news_classifier.models import Headline


def _headline(text: str, source: str = "bankier") -> Headline:
    return Headline(
        headline=text, source=source, published_at=datetime(2026, 9, 17, 12, 0, 0)
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


def test_dedupe_pending_by_text_collapses_cross_source_duplicate() -> None:
    # issue #121: bankier's two RSS categories cross-post the same story --
    # headline_key() treats them as distinct (different source), so
    # dedup must happen on text alone, before that key is ever checked.
    first = _headline("Orlen podaje wyniki finansowe", source="bankier")
    second = _headline("Orlen podaje wyniki finansowe", source="bankier-wiadomosci")

    result = dedupe_pending_by_text([first, second])

    assert result == [first]  # first occurrence wins


def test_dedupe_pending_by_text_normalizes_whitespace_and_case() -> None:
    first = _headline("Orlen  podaje wyniki")
    second = _headline("orlen podaje WYNIKI ")

    result = dedupe_pending_by_text([first, second])

    assert result == [first]


def test_dedupe_pending_by_text_keeps_distinct_headlines() -> None:
    a, b = _headline("a"), _headline("b")

    result = dedupe_pending_by_text([a, b])

    assert result == [a, b]
