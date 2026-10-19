"""The owner's own Yahoo symbol and quote currency for an instrument the
import could not price (fin-ai-lab#285) -- pure data, no database, no
network. The valuation uses them over what the import found: the owner
enters them because the import found nothing, or the wrong listing."""

from dataclasses import dataclass
from typing import Literal

# What the owner can pick. "GBp" is a London listing quoted in pence, the
# way Yahoo states it; the valuation moves it with the pound's NBP rate.
QuoteCurrency = Literal["PLN", "USD", "EUR", "GBP", "GBp"]


@dataclass(frozen=True)
class InstrumentOverride:
    key: str  # per-broker instrument key (repository.position_key)
    yahoo_ticker: str | None = None
    quote_currency: str | None = None
