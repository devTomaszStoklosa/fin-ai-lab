"""XTB "Closed Positions" sheet (fin-ai-lab#249): one row per lot that has
been sold, with its volume, open and close time and what it cost and fetched.

The Open Positions sheet only knows what is still held. Together with the
open lots, these rows say what was held on every day since the account
started -- the open and close times bound each lot's holding period. Checked
on real exports: closed lots plus open lots reproduce the Cash Operations
purchases and sales to the cent.

Read through P1's public reader (docs/ARCHITECTURE.md rule 6), like lots.py.
Short lots (Type SELL) and lots without purchase or sale values (CFD and
crypto positions) cannot be priced as holdings and are counted, not guessed.
"""

import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from fin_ai_lab.portfolio_webapp.cash_operations import (
    POSITIONS_SHEET,
    CashOperationsError,
    account_currency,
)
from fin_ai_lab.portfolio_xray.parsers.reader import read_xlsx_sheets

CLOSED_SHEET = "Closed Positions"
_MAX_HEADER_SCAN_ROWS = 20
_REQUIRED_HEADERS = (
    "Instrument",
    "Ticker",
    "Type",
    "Volume",
    "Open Price",
    "Open Time (UTC)",
    "Close Time (UTC)",
    "Purchase Value",
    "Sale Value",
)


@dataclass(frozen=True)
class ClosedLot:
    lot_id: str  # row hash + occurrence number (the export has no lot ID)
    ticker: str
    instrument: str
    volume: Decimal
    open_price: Decimal  # per unit, in the listing's own currency
    opened_at: datetime
    closed_at: datetime
    purchase_value: Decimal  # in the account currency
    sale_value: Decimal  # in the account currency
    currency: str  # the account currency


@dataclass(frozen=True)
class ClosedLotsHistory:
    lots: list[ClosedLot]
    skipped_short: int = 0  # Type SELL
    skipped_unpriced: int = 0  # no purchase or sale value (CFD, crypto)
    unreadable_rows: int = 0


def extract_xtb_closed_lots(file_bytes: bytes) -> ClosedLotsHistory | None:
    """None when the file has no Closed Positions sheet, or an empty one.
    Raises CashOperationsError (shared with the Cash Operations reader) when
    the sheet has content that cannot be read."""
    sheets = read_xlsx_sheets(file_bytes)
    rows = sheets.get(CLOSED_SHEET)
    if rows is None or not any(cell is not None for row in rows for cell in row):
        return None
    currency = account_currency(sheets.get(POSITIONS_SHEET, []))
    if currency is None:
        raise CashOperationsError("Could not detect the account currency for Closed Positions")
    header_index = _header_index(rows)
    header = [str(cell) if cell is not None else "" for cell in rows[header_index]]
    column = {name: header.index(name) for name in _REQUIRED_HEADERS}

    lots: list[ClosedLot] = []
    seen: Counter[str] = Counter()
    short = unpriced = unreadable = 0
    for row in rows[header_index + 1 :]:
        lot_type = str(row[column["Type"]] or "").strip().upper()
        if not row[column["Instrument"]] or not lot_type:
            continue  # blank rows and the trailing "Total" row
        if lot_type != "BUY":
            short += 1
            continue
        if row[column["Purchase Value"]] in (None, "") or row[column["Sale Value"]] in (None, ""):
            unpriced += 1
            continue
        digest = hashlib.sha256("|".join(str(cell) for cell in row).encode()).hexdigest()[:24]
        lot = _parse_row(row, column, f"{digest}:{seen[digest]}", currency)
        seen[digest] += 1
        if lot is None:
            unreadable += 1
        else:
            lots.append(lot)
    return ClosedLotsHistory(lots, short, unpriced, unreadable)


def _header_index(rows: list[tuple[object, ...]]) -> int:
    for index, row in enumerate(rows[:_MAX_HEADER_SCAN_ROWS]):
        cells = {str(cell) for cell in row if cell is not None}
        if all(name in cells for name in _REQUIRED_HEADERS):
            return index
    raise CashOperationsError(f"No header row in the '{CLOSED_SHEET}' sheet")


def _parse_row(
    row: tuple[object, ...], column: dict[str, int], lot_id: str, currency: str
) -> ClosedLot | None:
    opened_at = row[column["Open Time (UTC)"]]
    closed_at = row[column["Close Time (UTC)"]]
    if not isinstance(opened_at, datetime) or not isinstance(closed_at, datetime):
        return None
    try:
        volume = Decimal(str(row[column["Volume"]]))
        open_price = Decimal(str(row[column["Open Price"]]))
        purchase = Decimal(str(row[column["Purchase Value"]]))
        sale = Decimal(str(row[column["Sale Value"]]))
    except InvalidOperation:
        return None
    if volume <= 0:
        return None
    return ClosedLot(
        lot_id=lot_id,
        ticker=str(row[column["Ticker"]]),
        instrument=str(row[column["Instrument"]]),
        volume=volume,
        open_price=open_price,
        opened_at=opened_at,
        closed_at=closed_at,
        purchase_value=purchase,
        sale_value=sale,
        currency=currency,
    )
