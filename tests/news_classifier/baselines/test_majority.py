from datetime import datetime

from fin_ai_lab.news_classifier.baselines.majority import classify_majority
from fin_ai_lab.news_classifier.models import Headline, Label


def _headline() -> Headline:
    return Headline(headline="Cokolwiek", source="bankier", published_at=datetime(2026, 9, 17))


def test_classify_majority_predicts_the_most_common_labels() -> None:
    training_labels = [
        Label(sentiment="positive", event_type="wyniki finansowe", tickers=["PKN"]),
        Label(sentiment="positive", event_type="wyniki finansowe", tickers=[]),
        Label(sentiment="negative", event_type="inne", tickers=[]),
    ]

    result = classify_majority(_headline(), training_labels=training_labels)

    assert result.sentiment == "positive"
    assert result.event_type == "wyniki finansowe"
    assert result.tickers == []


def test_classify_majority_rejects_empty_training_set() -> None:
    try:
        classify_majority(_headline(), training_labels=[])
        assert False, "expected ValueError"
    except ValueError:
        pass
