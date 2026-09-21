from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ValidationError

from fin_ai_lab.portfolio_xray.canonical import AccountType, Position
from fin_ai_lab.portfolio_xray.parsers.reader import (
    apply_row_filter,
    find_matching_config,
    read_xlsx_sheets,
    rows_as_dicts,
)
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry

# ASSUMPTION: only categories seen in the sample XTB export are mapped;
# anything else falls back to "other" rather than failing the import.
CATEGORY_TO_ASSET_CLASS = {
    "ETF": "etf",
    "STOCK": "equity",
    "STC": "equity",
    "CRYPTO": "crypto",
    "FX": "derivative",
    "CFD": "derivative",
}


class ImportResult(BaseModel):
    positions: list[Position]
    errors: list[str]
    warnings: list[str]


def import_xlsx(
    file_bytes: bytes,
    *,
    valuation_date: date,
    account_type: AccountType,
    market_currency: str,
    registry: ParserRegistry,
) -> ImportResult:
    sheets = read_xlsx_sheets(file_bytes)
    match = find_matching_config(sheets, registry)
    if match is None:
        return ImportResult(positions=[], errors=["Unknown file format"], warnings=[])

    config, sheet_name, header_row = match
    rows = rows_as_dicts(sheets[sheet_name], header_row)
    rows = apply_row_filter(rows, config.row_filter)

    positions: list[Position] = []
    errors: list[str] = []
    for row_number, row in rows:
        try:
            position = build_position(
                row,
                config.column_mapping,
                broker=config.broker,
                account_type=account_type,
                market_currency=market_currency,
                valuation_date=valuation_date,
            )
        except ValidationError as exc:
            message = exc.errors()[0]["msg"].removeprefix("Value error, ")
            errors.append(f"{message} in row {row_number}")
        else:
            positions.append(position)

    if errors:
        return ImportResult(positions=[], errors=errors, warnings=[])

    merged, warnings = deduplicate_positions(positions)
    return ImportResult(positions=merged, errors=[], warnings=warnings)


def build_position(
    row: dict[str, object],
    column_mapping: dict[str, str],
    *,
    broker: str,
    account_type: AccountType,
    market_currency: str,
    valuation_date: date,
) -> Position:
    mapped = {column_mapping[key]: value for key, value in row.items() if key in column_mapping}

    raw_category = str(mapped.pop("asset_class", "") or "").upper()
    asset_class = CATEGORY_TO_ASSET_CLASS.get(raw_category, "other")

    quantity = mapped.pop("quantity", None)
    market_value = mapped.pop("market_value", None)
    avg_cost = mapped.pop("avg_cost", None)
    net_profit_pct = mapped.pop("net_profit_pct", None)
    isin = mapped.pop("isin", None)

    quantity_decimal = Decimal(str(quantity))
    market_value_decimal = Decimal(str(market_value)) if market_value is not None else None
    avg_cost_decimal = Decimal(str(avg_cost)) if avg_cost is not None else None

    derived_avg_cost = _derive_avg_cost_from_broker_return(
        market_value_decimal, net_profit_pct, quantity_decimal
    )
    if derived_avg_cost is not None:
        avg_cost_decimal = derived_avg_cost

    return Position(
        broker=broker,
        account_type=account_type,
        instrument_name=str(mapped.get("instrument_name", "")),
        isin=str(isin) if isin else None,
        symbol=str(mapped["symbol"]) if mapped.get("symbol") is not None else None,
        asset_class=asset_class,
        quantity=quantity_decimal,
        avg_cost=avg_cost_decimal,
        cost_currency=market_currency if avg_cost_decimal is not None else None,
        market_value=market_value_decimal,
        market_currency=market_currency if market_value_decimal is not None else None,
        valuation_date=valuation_date,
    )


def _derive_avg_cost_from_broker_return(
    market_value: Decimal | None, net_profit_pct: object, quantity: Decimal
) -> Decimal | None:
    # Some brokers (XTB's "Open Positions" export) report a per-share price
    # ("Open price") in the instrument's own trading currency, but "Value"
    # and this broker-computed return % are always in the account currency
    # -- import_xlsx has only one market_currency for the whole file, so
    # trusting "Open price" as if it were already in that currency silently
    # mislabels it for foreign-listed instruments (see issue #188). Deriving
    # cost from the account-currency value and the broker's own return %
    # sidesteps that instead of guessing an FX rate.
    if net_profit_pct in (None, "") or market_value is None or quantity <= 0:
        return None
    cost_factor = 1 + Decimal(str(net_profit_pct)) / 100
    if cost_factor == 0:
        return None
    return market_value / cost_factor / quantity


def _dedup_key(position: Position) -> tuple[str, str, str | None]:
    return (position.broker, position.account_type, position.symbol)


def deduplicate_positions(positions: list[Position]) -> tuple[list[Position], list[str]]:
    merged: dict[tuple[str, str, str | None], Position] = {}
    warnings: list[str] = []

    for position in positions:
        key = _dedup_key(position)
        existing = merged.get(key)
        if existing is None:
            merged[key] = position
            continue

        total_quantity = existing.quantity + position.quantity
        merged[key] = existing.model_copy(
            update={
                "quantity": total_quantity,
                "market_value": _sum_optional(existing.market_value, position.market_value),
                "avg_cost": _weighted_avg_cost(existing, position, total_quantity),
            }
        )
        warnings.append(f"Merged duplicate position for symbol '{position.symbol}'")

    return list(merged.values()), warnings


def _sum_optional(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None and right is None:
        return None
    return (left or Decimal(0)) + (right or Decimal(0))


def _weighted_avg_cost(left: Position, right: Position, total_quantity: Decimal) -> Decimal | None:
    if left.avg_cost is None or right.avg_cost is None or total_quantity == 0:
        return left.avg_cost
    weighted = left.avg_cost * left.quantity + right.avg_cost * right.quantity
    return weighted / total_quantity
