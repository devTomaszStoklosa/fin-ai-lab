"""Bossa "historia finansowa" export (fin-ai-lab#246): the cash history of one
brokerage account, PLN and USD together -- `data;tytuł operacji;szczegóły;
kwota;waluta`, cp1250, semicolons, comma decimals.

One file carries everything the portfolio needs from Bossa:
- trade settlements ("Rozliczenie transakcji kupna/sprzedaży"), whose
  details text holds the name, ISIN, quantity, price and currency, and whose
  amount is the net figure after commission -- the same trades `hisPW` lists,
  minus the time of day;
- dividends, deposits, fees (cash operations, like XTB's Cash Operations).

Only titles seen in a real export are mapped; anything else is reported, not
guessed. Read here rather than in P1's ledger.py (docs/ARCHITECTURE.md rule
6): ledger.py owns the trade shape, this owns one more way to obtain it.
"""

import csv
import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Literal

from fin_ai_lab.portfolio_webapp.cash_operations import CashOperation, OperationKind
from fin_ai_lab.portfolio_xray.ledger import BossaTransaction

_ENCODING = "cp1250"
_DELIMITER = ";"
_HEADER = ["data", "tytuł operacji", "szczegóły", "kwota", "waluta"]

_BUY_TITLE = "Rozliczenie transakcji kupna"
_SELL_TITLE = "Rozliczenie transakcji sprzedaży"

# Title prefix -> what the row is. Order does not matter, prefixes differ.
_KIND_BY_PREFIX: dict[str, OperationKind] = {
    "Wypłata dywidendy": "dividend",  # cash credited, whether net or gross
    "Korekta dywidendy": "dividend",
    "Opłata za transakcję": "other",
    "Zwrot prowizji": "other",
    "Przelew do DM BOŚ": "transfer",  # a deposit
}
# Internal PLN/USD move: neither an inflow, an outflow nor a result.
_IGNORED_PREFIXES = ("Wymiana waluty",)

# "DexCom (US2521311074) 20 x 85.60 USD nr Z00412477384"; a price may carry a
# thousands space ("1 790.00").
_DETAILS = re.compile(
    r"^(?P<name>.+?)\s+\((?P<isin>[A-Z]{2}[A-Z0-9]{9}[0-9])\)\s+"
    r"(?P<quantity>[\d\s.]+?)\s+x\s+(?P<price>[\d\s.]+?)\s+(?P<currency>[A-Z]{3})\s+nr\s+\S+$"
)


# "Wypłata dywidendy PEKAO", "Wypłata dywidendy netto HCA 85% USD",
# "Wypłata dywidendy brutto HIDD USD", "Korekta dywidendy ARR": the company
# is named only here -- by its short name on the GPW, by its ticker abroad.
_DIVIDEND_TITLE = re.compile(
    r"^(?P<kind>Wypłata|Korekta) dywidendy(?:\s+(?P<form>netto|brutto))?\s+(?P<code>\S+)"
    r"(?:\s+(?P<paid>\d+)%)?"
)


@dataclass(frozen=True)
class DividendTitle:
    code: str  # as the title names the company: "PEKAO", "HCA"
    is_correction: bool
    # #267: tax withheld at source as the title states it -- "netto 85%"
    # is 0.15, "brutto" is 0; None when the title doesn't say.
    withheld: Decimal | None = None


@dataclass(frozen=True)
class FinancialHistory:
    transactions: list[BossaTransaction]
    operations: list[CashOperation]
    unknown_titles: list[str] = field(default_factory=list)
    unreadable_rows: int = 0


def is_financial_history(file_bytes: bytes) -> bool:
    """True when the first line is this export's header."""
    try:
        first_line = file_bytes.decode(_ENCODING).lstrip("﻿").splitlines()[0]
    except (UnicodeDecodeError, IndexError):
        return False
    return [cell.strip().casefold() for cell in first_line.split(_DELIMITER)] == _HEADER


def parse_financial_history(file_bytes: bytes) -> FinancialHistory:
    text = file_bytes.decode(_ENCODING).lstrip("﻿")
    rows = list(csv.reader(StringIO(text), delimiter=_DELIMITER))[1:]

    transactions: list[BossaTransaction] = []
    operations: list[CashOperation] = []
    unknown: dict[str, None] = {}
    unreadable = 0
    seen_rows: Counter[str] = Counter()
    for row in rows:
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != len(_HEADER):
            unreadable += 1
            continue
        day_text, title, details, amount_text, currency = (cell.strip() for cell in row)
        title = title.rstrip(":")
        if title.startswith(_IGNORED_PREFIXES):
            continue
        try:
            day = date.fromisoformat(day_text)
            amount = _decimal(amount_text)
        except (ValueError, InvalidOperation):
            unreadable += 1
            continue

        if title in (_BUY_TITLE, _SELL_TITLE):
            side = "buy" if title == _BUY_TITLE else "sell"
            trade = _trade(day, side, details, amount, currency)
            if trade is None:
                unreadable += 1
            else:
                transactions.append(trade)
            continue

        kind: OperationKind | None = next(
            (k for prefix, k in _KIND_BY_PREFIX.items() if title.startswith(prefix)), None
        )
        if kind is None:
            unknown[title] = None
            continue
        # The file has no operation ID: identical rows are told apart by
        # their number within the file, so two equal fees on one day both
        # count, and a later overlapping export adds nothing twice.
        digest = hashlib.sha256("|".join(row).encode("utf-8")).hexdigest()[:24]
        occurrence = seen_rows[digest]
        seen_rows[digest] += 1
        operations.append(
            CashOperation(
                op_id=f"bossa:{digest}:{occurrence}",
                kind=kind,
                op_type=title,
                instrument=None,
                occurred_at=datetime.combine(day, time.min),
                amount=amount,
                currency=currency,
            )
        )
    return FinancialHistory(transactions, operations, list(unknown), unreadable)


def parse_dividend_title(title: str) -> DividendTitle | None:
    """The company a dividend row names (#265), read from its stored title
    -- so rows imported before this existed need no re-import. None when the
    title names none."""
    match = _DIVIDEND_TITLE.match(title.strip())
    if match is None:
        return None
    withheld = None
    if match["form"] == "brutto":
        withheld = Decimal(0)
    elif match["form"] == "netto" and match["paid"] is not None:
        withheld = 1 - Decimal(match["paid"]) / 100
    return DividendTitle(
        code=match["code"], is_correction=match["kind"] == "Korekta", withheld=withheld
    )


def _trade(
    day: date, side: Literal["buy", "sell"], details: str, amount: Decimal, currency: str
) -> BossaTransaction | None:
    match = _DETAILS.match(details)
    if match is None or match["currency"] != currency:
        return None
    try:
        quantity = _plain_decimal(match["quantity"])
        price = _plain_decimal(match["price"])
    except InvalidOperation:
        return None
    value = quantity * price
    net = abs(amount)
    # The file lists no time of day. Buys go first within a day, so a replay
    # never sees a sale before the purchase it may depend on.
    moment = time(0, 0, 0) if side == "buy" else time(0, 0, 1)
    return BossaTransaction(
        executed_at=datetime.combine(day, moment),
        instrument_name=match["name"].strip(),
        isin=match["isin"],
        side=side,
        quantity=quantity,
        price=price,
        value=value,
        commission=abs(net - value),
        net_value=net,
        currency=currency,
    )


def _decimal(text: str) -> Decimal:
    return Decimal(text.replace("\xa0", "").replace(" ", "").replace(",", "."))


def _plain_decimal(text: str) -> Decimal:
    return Decimal(re.sub(r"\s", "", text))
