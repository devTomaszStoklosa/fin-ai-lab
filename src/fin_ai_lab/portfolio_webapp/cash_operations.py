"""XTB "Cash Operations" sheet (fin-ai-lab#241): every purchase, sale,
dividend, interest payment and fee of an account, each with XTB's own ID.

This is what the investment result needs beyond the open positions: what was
paid for every purchase, what every sale brought in, and what the account
earned on the side. Read here through P1's public reader
(docs/ARCHITECTURE.md rule 6), like lots.py.

Deposits and withdrawals ("transfer") never enter the result itself -- that
is how much the purchases are worth more than they cost -- but their net sum
is the money the owner actually put in, the base the result is compared to
as a percentage. A type this file does not know is reported, never guessed at.

The Ticker and Comment columns (#265) say which instrument a dividend came
from ("MSFT.US", the symbol XTB keys its positions by) and what it paid per
share ("MSFT.US USD 0.91/ SHR"). Both are optional: an export without them
still imports.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from fin_ai_lab.portfolio_xray.parsers.reader import read_xlsx_sheets

# A dividend row's comment: "MSFT.US USD 0.91/ SHR", "TTE.FR EUR 0.8500/ SHR".
# A correction starts with "corr " and a tax row reads "... WHT 15%" -- both
# deliberately don't match.
_PER_SHARE_COMMENT = re.compile(r"^\S+ (?P<currency>[A-Z]{3}) (?P<amount>\d+(?:\.\d+)?)/ SHR$")
# A withholding-tax row's comment: "MSFT.US USD WHT 15%", "TTE.FR EUR WHT 25%".
_WITHHOLDING_COMMENT = re.compile(r"^\S+ [A-Z]{3} WHT (?P<rate>\d+(?:\.\d+)?)%$")

CASH_SHEET = "Cash Operations"
POSITIONS_SHEET = "Open Positions"
_CURRENCY_LABEL = "Open position value"
_CURRENCY_COLUMN_OFFSET = 2
_MAX_HEADER_SCAN_ROWS = 20

OperationKind = Literal["purchase", "sale", "dividend", "interest", "other", "transfer"]

# Only the types observed in real exports (PLN, USD and EUR accounts).
_KIND_BY_TYPE: dict[str, OperationKind] = {
    "Stock purchase": "purchase",
    "Stock sell": "sale",
    "Dividend": "dividend",
    "Withholding tax": "dividend",  # tax taken from a dividend
    "Free funds interest": "interest",
    "Free funds interest tax": "interest",
    "SEC fee": "other",
    "Stamp duty": "other",
    "Swap": "other",
    "Tax IFTT": "other",
    "Close trade": "other",
    "Correction": "other",
    "Deposit": "transfer",  # positive amount
    "Withdrawal": "transfer",  # negative amount
}
_IGNORED_TYPES = {"Total"}
_REQUIRED_HEADERS = ("Type", "Time", "Amount", "ID")
_OPTIONAL_HEADERS = ("Instrument", "Ticker", "Comment")


class CashOperationsError(ValueError):
    """The sheet is there but cannot be read (no header, no account currency)."""


@dataclass(frozen=True)
class CashOperation:
    op_id: str
    kind: OperationKind
    op_type: str  # XTB's own label
    instrument: str | None
    occurred_at: datetime
    amount: Decimal  # signed, in `currency`
    currency: str
    ticker: str | None = None  # XTB's own symbol ("MSFT.US")
    comment: str | None = None  # XTB's comment ("MSFT.US USD 0.91/ SHR")


@dataclass(frozen=True)
class CashHistory:
    operations: list[CashOperation]
    unknown_types: list[str] = field(default_factory=list)
    unreadable_rows: int = 0


def extract_xtb_cash_operations(file_bytes: bytes) -> CashHistory | None:
    """None when the file has no Cash Operations sheet, or an empty one (not
    an XTB export, or one without history). Raises CashOperationsError when
    the sheet has content that cannot be read."""
    sheets = read_xlsx_sheets(file_bytes)
    rows = sheets.get(CASH_SHEET)
    if rows is None or not any(cell is not None for row in rows for cell in row):
        return None
    currency = account_currency(sheets.get(POSITIONS_SHEET, []))
    if currency is None:
        raise CashOperationsError(
            f"Could not detect the account currency from the '{_CURRENCY_LABEL}' row"
        )
    header_index = _header_index(rows)
    header = [str(cell) if cell is not None else "" for cell in rows[header_index]]
    column = {
        name: header.index(name)
        for name in (*_REQUIRED_HEADERS, *_OPTIONAL_HEADERS)
        if name in header
    }

    operations: list[CashOperation] = []
    unknown: dict[str, None] = {}
    unreadable = 0
    for row in rows[header_index + 1 :]:
        op_type = str(row[column["Type"]] or "").strip()
        if not op_type or op_type in _IGNORED_TYPES:
            continue
        kind = _KIND_BY_TYPE.get(op_type)
        if kind is None:
            unknown[op_type] = None
            continue
        parsed = _parse_row(row, column, kind, op_type, currency)
        if parsed is None:
            unreadable += 1
        else:
            operations.append(parsed)
    return CashHistory(operations, list(unknown), unreadable)


def dividend_per_share(comment: str | None) -> tuple[str, Decimal] | None:
    """What a dividend paid per share, as XTB states it in the comment
    (#266): (currency, amount). None for any other comment."""
    match = _PER_SHARE_COMMENT.match((comment or "").strip())
    if match is None:
        return None
    return match["currency"], Decimal(match["amount"])


def withholding_rate(comment: str | None) -> Decimal | None:
    """The tax withheld at source as XTB states it ("WHT 15%" -> 0.15),
    #267. None for any other comment, a correction included."""
    match = _WITHHOLDING_COMMENT.match((comment or "").strip())
    return Decimal(match["rate"]) / 100 if match else None


def _header_index(rows: list[tuple[object, ...]]) -> int:
    for index, row in enumerate(rows[:_MAX_HEADER_SCAN_ROWS]):
        cells = {str(cell) for cell in row if cell is not None}
        if all(name in cells for name in _REQUIRED_HEADERS):
            return index
    raise CashOperationsError(
        f"No header row with {', '.join(_REQUIRED_HEADERS)} in the '{CASH_SHEET}' sheet"
    )


def account_currency(rows: list[tuple[object, ...]]) -> str | None:
    for row in rows:
        for index, cell in enumerate(row):
            if cell != _CURRENCY_LABEL:
                continue
            at = index + _CURRENCY_COLUMN_OFFSET
            if at < len(row) and row[at] is not None:
                return str(row[at])
    return None


def _parse_row(
    row: tuple[object, ...],
    column: dict[str, int],
    kind: OperationKind,
    op_type: str,
    currency: str,
) -> CashOperation | None:
    op_id = row[column["ID"]]
    occurred_at = row[column["Time"]]
    if op_id in (None, "") or not isinstance(occurred_at, datetime):
        return None
    try:
        amount = Decimal(str(row[column["Amount"]]))
    except InvalidOperation:
        return None
    return CashOperation(
        op_id=str(op_id),
        kind=kind,
        op_type=op_type,
        instrument=_optional_text(row, column, "Instrument"),
        occurred_at=occurred_at,
        amount=amount,
        currency=currency,
        ticker=_optional_text(row, column, "Ticker"),
        comment=_optional_text(row, column, "Comment"),
    )


def _optional_text(row: tuple[object, ...], column: dict[str, int], name: str) -> str | None:
    if name not in column or column[name] >= len(row):
        return None
    value = row[column[name]]
    text = str(value).strip() if value is not None else ""
    return text or None
