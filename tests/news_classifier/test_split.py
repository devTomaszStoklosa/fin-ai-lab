from datetime import datetime, timedelta

from fin_ai_lab.news_classifier.models import Headline, Label, LabeledHeadline
from fin_ai_lab.news_classifier.split import split_chronological


def _item(headline: str, day_offset: int) -> LabeledHeadline:
    return LabeledHeadline(
        headline=Headline(
            headline=headline,
            source="bankier",
            published_at=datetime(2026, 1, 1) + timedelta(days=day_offset),
        ),
        label=Label(sentiment="neutral", event_type="inne", tickers=[]),
        source_model="teacher",
    )


def test_split_chronological_orders_oldest_to_newest_across_splits() -> None:
    items = [_item(f"headline {i}", day_offset=i) for i in range(10)]

    train, dev, test = split_chronological(items, train=0.7, dev=0.15, test=0.15)

    assert len(train) == 7
    assert len(dev) == 2
    assert len(test) == 1
    assert train[-1].headline.published_at < dev[0].headline.published_at
    assert dev[-1].headline.published_at < test[0].headline.published_at


def test_split_chronological_removes_near_duplicate_headlines() -> None:
    items = [
        _item("Spółka X ogłasza wyniki", day_offset=0),
        _item("  spółka   x ogłasza wyniki  ", day_offset=1),
        _item("Inny nagłówek", day_offset=2),
    ]

    train, dev, test = split_chronological(items, train=1.0, dev=0.0, test=0.0)

    assert len(train) == 2
    assert len(dev) == 0
    assert len(test) == 0


def test_split_chronological_rejects_ratios_not_summing_to_one() -> None:
    try:
        split_chronological([], train=0.5, dev=0.3, test=0.1)
        assert False, "expected ValueError"
    except ValueError:
        pass
