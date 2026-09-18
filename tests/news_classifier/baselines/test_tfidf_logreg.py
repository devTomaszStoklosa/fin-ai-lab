from datetime import datetime

import pytest

pytest.importorskip("sklearn")

from fin_ai_lab.news_classifier.baselines.tfidf_logreg import (  # noqa: E402
    TfidfLogRegModel,
    classify_tfidf_logreg,
)
from fin_ai_lab.news_classifier.models import Headline, Label, LabeledHeadline  # noqa: E402


def _labeled(headline: str, sentiment: str, event_type: str) -> LabeledHeadline:
    return LabeledHeadline(
        headline=Headline(headline=headline, source="bankier", published_at=datetime(2026, 9, 17)),
        label=Label(sentiment=sentiment, event_type=event_type, tickers=[]),
        source_model="teacher",
    )


def _training_set() -> list[LabeledHeadline]:
    return [
        _labeled("Orlen podaje rekordowe zyski", "positive", "wyniki finansowe"),
        _labeled("Orlen z dobrymi wynikami kwartalnymi", "positive", "wyniki finansowe"),
        _labeled("Spor sadowy przeciwko spolce", "negative", "spór prawny"),
        _labeled("Proces sadowy w toku", "negative", "spór prawny"),
    ]


def test_tfidf_logreg_predicts_a_known_category_pattern() -> None:
    model = TfidfLogRegModel.fit(_training_set())
    headline = Headline(
        headline="Spolka ogloasza swietne zyski", source="bankier",
        published_at=datetime(2026, 9, 18),
    )

    result = classify_tfidf_logreg(headline, model)

    assert result.sentiment in ("positive", "negative")
    assert result.event_type in ("wyniki finansowe", "spór prawny")


def test_tfidf_logreg_matches_a_known_company_name_to_its_ticker() -> None:
    model = TfidfLogRegModel.fit(_training_set())
    headline = Headline(
        headline="PKN Orlen ogloasza swietne zyski", source="bankier",
        published_at=datetime(2026, 9, 18),
    )

    result = classify_tfidf_logreg(headline, model)

    assert "PKN" in result.tickers


def test_tfidf_logreg_fit_rejects_empty_training_set() -> None:
    try:
        TfidfLogRegModel.fit([])
        assert False, "expected ValueError"
    except ValueError:
        pass
