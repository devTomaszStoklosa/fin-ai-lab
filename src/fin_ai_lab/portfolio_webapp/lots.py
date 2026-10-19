from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl.utils.datetime import from_excel

from fin_ai_lab.portfolio_xray.parsers.reader import (
    find_matching_config,
    read_xlsx_sheets,
    rows_as_dicts,
)
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry

# XTB's "Open Positions" sheet interleaves one summary row per instrument
# (Category set -- the only rows P1's parser config keeps) with one detail
# row per purchase ("lot": Type set, Category blank). Only the detail rows
# say *when* each part of a position was bought, which is what lets the
# value history (portfolio-webapp-S10) start before the first import
# instead of on the day of it. P1 has no use for lots, so this reads them
# here through P1's public reader functions instead of widening P1's
# canonical Position (docs/ARCHITECTURE.md rule 6).
XTB_BROKER = "xtb"
_CATEGORY_COLUMN = "Category"
_TYPE_COLUMN = "Type"
_TICKER_COLUMN = "Ticker"
_VOLUME_COLUMN = "Volume"
_LOT_REF_COLUMN = "Instrument/Position"
_OPEN_TIME_COLUMN = "Open time (UTC)"

# ASSUMPTION: the real export's "Open time (UTC)" cell format has not been
# observed in this repo yet (the synthetic fixture leaves it empty) --
# openpyxl hands back a datetime when the cell is typed as a date, so that
# is tried first; these string shapes are the ones XTB's own UI uses. A
# value matching none of them drops just that lot, never the import.
_OPEN_TIME_FORMATS = (
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


@dataclass(frozen=True)
class OpenLot:
    symbol: str
    lot_ref: str
    quantity: Decimal
    opened_on: date


def extract_xtb_open_lots(file_bytes: bytes, registry: ParserRegistry) -> list[OpenLot]:
    """Every long (BUY) lot of an XTB Open Positions export whose open date
    can be read. Anything that isn't an XTB export yields no lots -- never
    an error, since lots only refine the history; the import itself does
    not depend on them."""
    sheets = read_xlsx_sheets(file_bytes)
    match = find_matching_config(sheets, registry)
    if match is None:
        return []
    config, sheet_name, header_row = match
    if config.broker != XTB_BROKER:
        return []

    lots: list[OpenLot] = []
    for _row_number, row in rows_as_dicts(sheets[sheet_name], header_row):
        if row.get(_CATEGORY_COLUMN):
            continue  # summary row, already a Position
        # Short lots (SELL, CFDs) need a sign-aware history -- out of scope,
        # same line P1's own _return_pct draws for quantity <= 0.
        if str(row.get(_TYPE_COLUMN) or "").strip().upper() != "BUY":
            continue
        symbol = row.get(_TICKER_COLUMN)
        quantity = _as_decimal(row.get(_VOLUME_COLUMN))
        opened_on = parse_open_time(row.get(_OPEN_TIME_COLUMN))
        if not symbol or quantity is None or quantity <= 0 or opened_on is None:
            continue
        lots.append(
            OpenLot(
                symbol=str(symbol),
                lot_ref=str(row.get(_LOT_REF_COLUMN) or ""),
                quantity=quantity,
                opened_on=opened_on,
            )
        )
    return lots


def lots_matching_quantity(
    lots: Iterable[OpenLot], quantity_by_symbol: dict[str, Decimal]
) -> dict[str, list[OpenLot]]:
    """Lots grouped by symbol, kept only where they add up to exactly the
    position's own quantity. A partial set (e.g. one lot's open date was
    unreadable) would understate every day before the import, so such a
    position gets no lots at all and its history simply starts on the
    import date, like any broker without lot detail."""
    grouped: dict[str, list[OpenLot]] = {}
    for lot in lots:
        grouped.setdefault(lot.symbol, []).append(lot)
    return {
        symbol: symbol_lots
        for symbol, symbol_lots in grouped.items()
        if symbol in quantity_by_symbol
        and sum((lot.quantity for lot in symbol_lots), Decimal(0)) == quantity_by_symbol[symbol]
    }


def parse_open_time(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        # An Excel serial date the cell wasn't formatted to show as one.
        try:
            return from_excel(value).date()
        except (ValueError, OverflowError, AttributeError):
            return None
    if isinstance(value, str):
        text = value.strip()
        for fmt in _OPEN_TIME_FORMATS:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return None


def _as_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None
