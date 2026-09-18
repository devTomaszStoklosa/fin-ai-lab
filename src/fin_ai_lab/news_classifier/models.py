from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Sentiment = Literal["negative", "neutral", "positive"]
EventType = Literal[
    "wyniki finansowe",
    "dywidenda",
    "emisja akcji",
    "skup akcji",
    "przejęcie lub fuzja",
    "zmiana w zarządzie",
    "prognoza",
    "decyzja lub kara regulatora",
    "spór prawny",
    "umowa lub kontrakt",
    "rekomendacja lub rating",
    "makro",
    "inne",
]


class Headline(BaseModel):
    headline: str
    lead: str | None = None
    source: str
    published_at: datetime
    language: Literal["pl"] = "pl"


class Label(BaseModel):
    sentiment: Sentiment
    event_type: EventType
    tickers: list[str]


class LabeledHeadline(BaseModel):
    headline: Headline
    label: Label
    source_model: str
