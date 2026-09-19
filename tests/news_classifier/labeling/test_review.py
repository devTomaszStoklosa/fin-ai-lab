import csv
from datetime import datetime
from pathlib import Path

import pytest

from fin_ai_lab.news_classifier.labeling.review import (
    _FIELDNAMES,
    build_golden_set,
    export_for_review,
    score_calibration,
)
from fin_ai_lab.news_classifier.models import Headline, Label, LabeledHeadline


def _labeled(text: str, sentiment: str, event_type: str, tickers: list[str]) -> LabeledHeadline:
    return LabeledHeadline(
        headline=Headline(
            headline=text, source="bankier", published_at=datetime(2026, 9, 18, 12, 0, 0)
        ),
        label=Label(sentiment=sentiment, event_type=event_type, tickers=tickers),
        source_model="teacher",
    )


def test_export_for_review_writes_no_teacher_columns(tmp_path: Path) -> None:
    corpus = [_labeled("Orlen podaje wyniki", "positive", "wyniki finansowe", ["PKN"])]
    output = tmp_path / "review.csv"

    sample = export_for_review(corpus, output, sample_size=10)

    assert sample == corpus
    with output.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["headline"] == "Orlen podaje wyniki"
    assert rows[0]["human_sentiment"] == ""
    assert set(_FIELDNAMES) == set(rows[0].keys())
    assert {"sentiment", "event_type", "tickers"}.isdisjoint(rows[0].keys())


def test_export_for_review_samples_deterministically(tmp_path: Path) -> None:
    corpus = [
        _labeled(f"Nagłówek {i}", "neutral", "inne", []) for i in range(20)
    ]
    output = tmp_path / "review.csv"

    first = export_for_review(corpus, output, sample_size=5)
    second = export_for_review(corpus, output, sample_size=5)

    assert [item.headline.headline for item in first] == [
        item.headline.headline for item in second
    ]
    assert len(first) == 5


def _write_reviewed(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_score_calibration_computes_kappa_for_reviewed_rows(tmp_path: Path) -> None:
    corpus = [
        _labeled("Orlen podaje wyniki", "positive", "wyniki finansowe", ["PKN"]),
        _labeled("Spółka X pozwana", "negative", "spór prawny", []),
    ]
    reviewed_path = tmp_path / "reviewed.csv"
    _write_reviewed(
        reviewed_path,
        [
            {
                "headline": "Orlen podaje wyniki",
                "lead": "",
                "source": "bankier",
                "published_at": "2026-09-18T12:00:00",
                "human_sentiment": "positive",
                "human_event_type": "wyniki finansowe",
                "human_tickers": "PKN",
            },
            {
                "headline": "Spółka X pozwana",
                "lead": "",
                "source": "bankier",
                "published_at": "2026-09-18T12:00:00",
                "human_sentiment": "negative",
                "human_event_type": "spór prawny",
                "human_tickers": "",
            },
        ],
    )

    report = score_calibration(corpus, reviewed_path)

    assert report["n_reviewed"] == 2
    assert report["n_exported"] == 2
    assert report["sentiment_kappa"] == 1.0
    assert report["event_type_kappa"] == 1.0
    assert report["tickers_exact_match_pct"] == 1.0


def test_score_calibration_skips_blank_rows_not_as_disagreement(tmp_path: Path) -> None:
    corpus = [
        _labeled("Orlen podaje wyniki", "positive", "wyniki finansowe", ["PKN"]),
        _labeled("Nieoceniony nagłówek", "neutral", "inne", []),
    ]
    reviewed_path = tmp_path / "reviewed.csv"
    _write_reviewed(
        reviewed_path,
        [
            {
                "headline": "Orlen podaje wyniki",
                "lead": "",
                "source": "bankier",
                "published_at": "2026-09-18T12:00:00",
                "human_sentiment": "positive",
                "human_event_type": "wyniki finansowe",
                "human_tickers": "PKN",
            },
            {
                "headline": "Nieoceniony nagłówek",
                "lead": "",
                "source": "bankier",
                "published_at": "2026-09-18T12:00:00",
                "human_sentiment": "",
                "human_event_type": "",
                "human_tickers": "",
            },
        ],
    )

    report = score_calibration(corpus, reviewed_path)

    assert report["n_reviewed"] == 1
    assert report["n_exported"] == 2


def test_score_calibration_counts_a_duplicate_headline_once(tmp_path: Path) -> None:
    # Same text from two feeds (e.g. bankier + bankier-wiadomosci) — the
    # corpus isn't deduped by text until split time, so this happens for
    # real (found live). One human judgment must not count twice.
    corpus = [
        _labeled("Orlen podaje wyniki", "positive", "wyniki finansowe", ["PKN"]),
        _labeled("Orlen podaje wyniki", "positive", "wyniki finansowe", ["PKN"]),
    ]
    reviewed_path = tmp_path / "reviewed.csv"
    _write_reviewed(
        reviewed_path,
        [
            {
                "headline": "Orlen podaje wyniki",
                "lead": "",
                "source": "bankier",
                "published_at": "2026-09-18T12:00:00",
                "human_sentiment": "positive",
                "human_event_type": "wyniki finansowe",
                "human_tickers": "PKN",
            }
        ],
    )

    report = score_calibration(corpus, reviewed_path)

    assert report["n_reviewed"] == 1


def test_score_calibration_raises_when_nothing_was_reviewed(tmp_path: Path) -> None:
    corpus = [_labeled("Orlen podaje wyniki", "positive", "wyniki finansowe", ["PKN"])]
    reviewed_path = tmp_path / "reviewed.csv"
    _write_reviewed(
        reviewed_path,
        [
            {
                "headline": "Orlen podaje wyniki",
                "lead": "",
                "source": "bankier",
                "published_at": "2026-09-18T12:00:00",
                "human_sentiment": "",
                "human_event_type": "",
                "human_tickers": "",
            }
        ],
    )

    with pytest.raises(ValueError):
        score_calibration(corpus, reviewed_path)


def test_build_golden_set_uses_human_labels_and_skips_blank_rows(tmp_path: Path) -> None:
    reviewed_path = tmp_path / "reviewed.csv"
    _write_reviewed(
        reviewed_path,
        [
            {
                "headline": "Orlen podaje wyniki",
                "lead": "Spółka informuje o wzroście przychodów",
                "source": "bankier",
                "published_at": "2026-09-18T12:00:00",
                "human_sentiment": "positive",
                "human_event_type": "wyniki finansowe",
                "human_tickers": "PKN",
            },
            {
                "headline": "Nieoceniony nagłówek",
                "lead": "",
                "source": "bankier",
                "published_at": "2026-09-18T12:00:00",
                "human_sentiment": "",
                "human_event_type": "",
                "human_tickers": "",
            },
        ],
    )

    golden = build_golden_set(reviewed_path)

    assert len(golden) == 1
    item = golden[0]
    assert item.headline.headline == "Orlen podaje wyniki"
    assert item.headline.lead == "Spółka informuje o wzroście przychodów"
    assert item.label.sentiment == "positive"
    assert item.label.event_type == "wyniki finansowe"
    assert item.label.tickers == ["PKN"]
    assert item.source_model == "human"


def test_build_golden_set_skips_a_row_with_an_invalid_label_value(tmp_path: Path) -> None:
    reviewed_path = tmp_path / "reviewed.csv"
    _write_reviewed(
        reviewed_path,
        [
            {
                "headline": "WIG wraca do wzrostów",
                "lead": "",
                "source": "bankier",
                "published_at": "2026-09-18T12:00:00",
                "human_sentiment": "positive",
                # Shorthand typo, not the exact "rekomendacja lub rating"
                # literal — real free-text input, not guessed.
                "human_event_type": "rekomendacja",
                "human_tickers": "",
            },
            {
                "headline": "Orlen podaje wyniki",
                "lead": "",
                "source": "bankier",
                "published_at": "2026-09-18T12:00:00",
                "human_sentiment": "positive",
                "human_event_type": "wyniki finansowe",
                "human_tickers": "PKN",
            },
        ],
    )

    golden = build_golden_set(reviewed_path)

    assert len(golden) == 1
    assert golden[0].headline.headline == "Orlen podaje wyniki"
