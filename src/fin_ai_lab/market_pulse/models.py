from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

Regime = Literal["risk-on", "neutral", "risk-off"]
Source = Literal["fred", "nbp-fx", "nbp-rate"]


class IndicatorObservation(BaseModel):
    series_id: str
    label: str
    value: Decimal
    unit: str
    as_of_date: date
    source: Source
    previous_value: Decimal | None = None
    change: Decimal | None = None


class RegimeResult(BaseModel):
    regime: Regime
    signals: list[str]


class Brief(BaseModel):
    date: date
    regime: Regime
    regime_rationale: list[str]
    indicators: list[IndicatorObservation]
    missing_sources: list[str]
    text: str


class NewsItem(BaseModel):
    title: str
    summary: str
    source: str
    link: str


class Alert(BaseModel):
    series_id: str
    previous_value: Decimal
    new_value: Decimal
    threshold: Decimal
    message: str
