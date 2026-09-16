from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

KNOWN_CURRENCIES = {"PLN", "USD", "EUR", "GBP"}

AccountType = Literal["regular", "ike", "ikze", "other"]
AssetClass = Literal["equity", "etf", "bond", "fund", "cash", "crypto", "derivative", "other"]
ResolutionStatus = Literal["resolved", "unresolved", "ambiguous"]


def isin_checksum_is_valid(isin: str) -> bool:
    if len(isin) != 12 or not isin[:2].isalpha() or not isin[-1].isdigit():
        return False
    expanded = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in isin[:-1])
    if not expanded.isdigit():
        return False

    total = 0
    double = True
    for digit_char in reversed(expanded):
        digit = int(digit_char)
        if double:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
        double = not double

    check_digit = (10 - total % 10) % 10
    return check_digit == int(isin[-1])


class Position(BaseModel):
    broker: str
    account_type: AccountType
    instrument_name: str
    isin: str | None = None
    symbol: str | None = None
    asset_class: AssetClass
    quantity: Decimal
    avg_cost: Decimal | None = None
    cost_currency: str | None = None
    market_value: Decimal | None = None
    market_currency: str | None = None
    valuation_date: date
    resolution_status: ResolutionStatus = "unresolved"
    figi: str | None = None
    ticker: str | None = None
    exchange_code: str | None = None
    identification_rule: str | None = None
    suspicious_cells: list[str] = []

    @field_validator("broker")
    @classmethod
    def _broker_known(cls, value: str) -> str:
        # Not a closed set: P1-S2 onboards new brokers at runtime (the LLM
        # correction loop), so "known" means "identified", not "in an
        # allowlist maintained here" — that would block onboarding itself.
        if not value:
            raise ValueError(f"Unknown broker '{value}'")
        return value

    @field_validator("instrument_name")
    @classmethod
    def _instrument_name_length(cls, value: str) -> str:
        if not 1 <= len(value) <= 200:
            raise ValueError("Missing instrument name")
        return value

    @field_validator("isin")
    @classmethod
    def _isin_checksum(cls, value: str | None) -> str | None:
        if value is not None and not isin_checksum_is_valid(value):
            raise ValueError("Invalid ISIN checksum")
        return value

    @model_validator(mode="after")
    def _cross_field_checks(self) -> "Position":
        if self.quantity == 0:
            raise ValueError("Quantity must be non-zero")
        if self.quantity < 0 and self.asset_class != "derivative":
            raise ValueError("Quantity must be non-zero")

        if self.avg_cost is not None and self.avg_cost < 0:
            raise ValueError("Negative average cost")
        if self.avg_cost is not None:
            _require_known_currency(self.cost_currency)

        market_value_negative = self.market_value is not None and self.market_value < 0
        if market_value_negative and self.asset_class != "derivative":
            raise ValueError("Negative market value")
        if self.market_value is not None:
            _require_known_currency(self.market_currency)

        if self.valuation_date > date.today():
            raise ValueError("Valuation date in the future")

        return self


class Portfolio(BaseModel):
    positions: list[Position]
    base_currency: Literal["PLN"] = "PLN"
    valuation_date: date


def _require_known_currency(currency: str | None) -> None:
    if currency is None or currency not in KNOWN_CURRENCIES:
        raise ValueError(f"Unknown currency '{currency or ''}'")
