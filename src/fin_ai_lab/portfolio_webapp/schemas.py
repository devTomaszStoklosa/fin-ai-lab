from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


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
