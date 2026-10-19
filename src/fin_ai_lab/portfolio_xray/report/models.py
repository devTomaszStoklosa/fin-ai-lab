from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from fin_ai_lab.portfolio_xray.metrics.risk import RiskMetrics
from fin_ai_lab.portfolio_xray.metrics.weights import WeightMetrics


class InstrumentMetadata(BaseModel):
    name: str
    category: str  # GICS-like sector for equity, else asset_class-derived category (REQ-030a)
    exchange_code: str | None = None
    currency: str | None = None


class MetricsJson(BaseModel):
    valuation_date: date
    base_currency: str
    weights: WeightMetrics
    risk: RiskMetrics | None = None
    allocation_by_category: dict[str, Decimal]
