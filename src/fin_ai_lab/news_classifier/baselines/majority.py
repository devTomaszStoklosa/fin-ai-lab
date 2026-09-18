from collections import Counter

from fin_ai_lab.news_classifier.models import Headline, Label


def classify_majority(headline: Headline, *, training_labels: list[Label]) -> Label:
    """docs/EVALS.md's class-imbalance baseline: always predicts the
    single most frequent sentiment and event_type seen in training,
    ignoring the headline's actual content entirely. `tickers` is always
    empty — "most common" has no sensible meaning for a per-headline set
    field, and an empty list is never wrong per REQ-002."""
    if not training_labels:
        raise ValueError("training_labels must not be empty")
    del headline  # baseline by definition, never looks at the input

    sentiment = Counter(label.sentiment for label in training_labels).most_common(1)[0][0]
    event_type = Counter(label.event_type for label in training_labels).most_common(1)[0][0]
    return Label(sentiment=sentiment, event_type=event_type, tickers=[])
