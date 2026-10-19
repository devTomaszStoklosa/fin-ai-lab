"""The owner's own valuations of a manual position (fin-ai-lab#288) -- an
asset no exchange quotes, a gold coin say -- pure data and rules, no
database, no network. A manual position is worth its purchase price from
its purchase date (the position's own valuation_date) and each valuation's
price from that valuation's day on; nothing in between is invented."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ManualValuation:
    valued_on: date
    unit_value: Decimal  # per unit, in PLN like every manual position


class ValuationDateError(Exception):
    pass


def current_unit_value(avg_cost: Decimal, valuations: list[ManualValuation]) -> Decimal:
    """The latest valuation's price, else the purchase price."""
    if not valuations:
        return avg_cost
    return max(valuations, key=lambda v: v.valued_on).unit_value


def market_value(
    quantity: Decimal, avg_cost: Decimal, valuations: list[ManualValuation]
) -> Decimal:
    """What the position's stored market_value follows, so metrics, aggregators,
    shares and the AI report see the current value without knowing about
    valuations at all."""
    return quantity * current_unit_value(avg_cost, valuations)


def validate_purchase_date(
    purchased_on: date, valuations: list[ManualValuation], today: date
) -> None:
    if purchased_on > today:
        raise ValuationDateError("Data zakupu nie może być w przyszłości.")
    earliest = min((v.valued_on for v in valuations), default=None)
    if earliest is not None and purchased_on > earliest:
        raise ValuationDateError(
            f"Data zakupu nie może być późniejsza niż najstarsza wycena ({earliest}) — "
            "najpierw usuń wyceny sprzed nowej daty zakupu."
        )


def validate_valuation_date(valued_on: date, purchased_on: date, today: date) -> None:
    if valued_on > today:
        raise ValuationDateError("Data wyceny nie może być w przyszłości.")
    if valued_on < purchased_on:
        raise ValuationDateError(
            f"Data wyceny nie może być wcześniejsza niż data zakupu ({purchased_on})."
        )
