from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from fin_ai_lab.portfolio_xray.canonical import AssetClass
from fin_ai_lab.portfolio_xray.parsers.config import ParserConfig


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    broker: str | None = None
    account_type: str | None = None


class PortfolioOut(BaseModel):
    id: UUID
    name: str
    broker: str | None
    account_type: str | None
    created_at: datetime


class PositionOut(BaseModel):
    id: UUID
    broker: str
    account_type: str
    instrument_name: str
    isin: str | None
    symbol: str | None
    asset_class: str
    quantity: Decimal
    avg_cost: Decimal | None
    cost_currency: str | None
    market_value: Decimal | None
    market_currency: str | None
    valuation_date: date
    resolution_status: str
    figi: str | None
    ticker: str | None
    exchange_code: str | None
    identification_rule: str | None
    return_pct: Decimal | None


class SnapshotOut(BaseModel):
    id: UUID
    portfolio_id: UUID
    broker: str
    valuation_date: date
    imported_at: datetime
    source_file_date_min: date | None
    source_file_date_max: date | None
    positions: list[PositionOut]


class ImportResponse(BaseModel):
    snapshot: SnapshotOut
    warnings: list[str]


class PositionPreviewOut(BaseModel):
    """A position as it would come out of a *proposed* (not yet saved)
    parser config -- no id, no resolution/FIGI fields, since nothing has
    been persisted or run through OpenFIGI yet."""

    instrument_name: str
    isin: str | None
    symbol: str | None
    asset_class: str
    quantity: Decimal
    avg_cost: Decimal | None
    cost_currency: str | None
    market_value: Decimal | None
    market_currency: str | None


class ProposePreview(BaseModel):
    config: ParserConfig
    positions: list[PositionPreviewOut]
    warnings: list[str]


class PositionCreate(BaseModel):
    instrument_name: str = Field(min_length=1, max_length=200)
    isin: str | None = None
    symbol: str | None = None
    asset_class: AssetClass
    quantity: Decimal = Field(gt=0)
    avg_cost: Decimal = Field(gt=0)


class PositionUpdate(PositionCreate):
    # Not auto-derived on update, unlike creation -- this is what lets the
    # owner move a manual position's valuation away from cost basis later.
    market_value: Decimal = Field(ge=0)


class MetricsOut(BaseModel):
    position_count: int
    total_value: Decimal | None
    base_currency: str
    hhi: Decimal | None
    effective_positions: Decimal | None
    top5_share: Decimal | None
    allocation_by_asset_class: dict[str, Decimal]
    allocation_by_currency: dict[str, Decimal]


class ReportOut(BaseModel):
    id: UUID
    snapshot_id: UUID
    generated_at: datetime
    model: str
    cost_usd: Decimal
    content_md: str
