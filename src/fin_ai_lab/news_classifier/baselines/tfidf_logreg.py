from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from fin_ai_lab.news_classifier.models import Headline, Label, LabeledHeadline
from fin_ai_lab.news_classifier.ticker_catalog import TICKER_CATALOG


@dataclass
class TfidfLogRegModel:
    vectorizer: TfidfVectorizer
    sentiment_clf: LogisticRegression
    event_type_clf: LogisticRegression

    @classmethod
    def fit(cls, training: list[LabeledHeadline]) -> "TfidfLogRegModel":
        if not training:
            raise ValueError("training must not be empty")

        texts = [_headline_text(item.headline) for item in training]
        vectorizer = TfidfVectorizer()
        features = vectorizer.fit_transform(texts)

        sentiment_clf = LogisticRegression(max_iter=1000).fit(
            features, [item.label.sentiment for item in training]
        )
        event_type_clf = LogisticRegression(max_iter=1000).fit(
            features, [item.label.event_type for item in training]
        )
        return cls(vectorizer, sentiment_clf, event_type_clf)


def classify_tfidf_logreg(headline: Headline, model: TfidfLogRegModel) -> Label:
    text = _headline_text(headline)
    features = model.vectorizer.transform([text])
    sentiment = model.sentiment_clf.predict(features)[0]
    event_type = model.event_type_clf.predict(features)[0]
    # TF-IDF+LR doesn't do ticker extraction — a deterministic company-name
    # match against the catalog is more defensible than an ML guess, and
    # keeps REQ-002's "never fuzzy-guess a ticker" property.
    tickers = _match_tickers(text)
    return Label(sentiment=sentiment, event_type=event_type, tickers=tickers)


def _headline_text(headline: Headline) -> str:
    return f"{headline.headline} {headline.lead or ''}".strip()


def _match_tickers(text: str) -> list[str]:
    lowered = text.lower()
    return [ticker for ticker, name in TICKER_CATALOG.items() if name.lower() in lowered]
