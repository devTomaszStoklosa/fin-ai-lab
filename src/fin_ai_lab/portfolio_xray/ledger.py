import csv
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from typing import Literal

from pydantic import BaseModel

from fin_ai_lab.portfolio_xray.canonical import AccountType, Position
from fin_ai_lab.portfolio_xray.metrics.price_history import fetch_price_history

# Bossa's own encoding/delimiter for this export (confirmed against the real
# file: bytes 0x9C/0xE6 decode as "ś"/"ć" only under cp1250, and the header
# is unparseable as UTF-8). Bossa has exactly one known export shape today,
# so this is a dedicated reader, not a generic configurable one like P1-S2's
# ParserConfig — that abstraction is for row-shaped exports (1 row = 1
# position); this file is transaction-shaped and needs aggregation instead.
_ENCODING = "cp1250"
_DELIMITER = ";"
_SIDE_MAP = {"K": "buy", "S": "sell"}


class BossaTransaction(BaseModel):
    executed_at: datetime
    instrument_name: str
    isin: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    value: Decimal
    commission: Decimal
    net_value: Decimal
    currency: str


def parse_bossa_csv(file_bytes: bytes) -> list[BossaTransaction]:
    text = file_bytes.decode(_ENCODING)
    reader = csv.DictReader(StringIO(text), delimiter=_DELIMITER)

    transactions = []
    for row_number, row in enumerate(reader, start=2):
        side = _SIDE_MAP.get(row["-"])
        if side is None:
            raise ValueError(f"Unknown transaction side '{row['-']}' in row {row_number}")
        transactions.append(
            BossaTransaction(
                executed_at=datetime.strptime(row["data"], "%d.%m.%Y %H:%M:%S"),
                instrument_name=row["papier"],
                isin=row["isin"],
                side=side,
                quantity=_parse_pl_decimal(row["ilość"]),
                price=_parse_pl_decimal(row["cena"]),
                value=_parse_pl_decimal(row["wartość"]),
                commission=_parse_pl_decimal(row["prowizja"]),
                net_value=_parse_pl_decimal(row["po prowizji"]),
                currency=row["waluta"],
            )
        )
    return transactions


def transactions_to_positions(
    transactions: list[BossaTransaction],
    *,
    account_type: AccountType,
    valuation_date: date,
) -> tuple[list[Position], list[str]]:
    """Deterministic replay, never a merge of two already-computed states
    (02-spec.md REQ-021): quantity is a running sum signed by side, average
    cost is a running weighted average of the buy legs (net of commission),
    reduced proportionally on each sell. Positions closed to zero are
    dropped; a position that would go negative means a sell the imported
    history has no matching buy for — most likely a gap before the earliest
    imported transaction (the one thing this function can actually detect;
    an overlap or a gap that never causes an oversell stays invisible here).
    """
    by_isin: dict[str, list[BossaTransaction]] = {}
    for transaction in transactions:
        by_isin.setdefault(transaction.isin, []).append(transaction)

    positions: list[Position] = []
    errors: list[str] = []
    for isin, isin_transactions in by_isin.items():
        ordered = sorted(isin_transactions, key=lambda t: t.executed_at)
        quantity = Decimal(0)
        cost_basis = Decimal(0)
        for transaction in ordered:
            if transaction.side == "buy":
                quantity += transaction.quantity
                cost_basis += transaction.net_value
            else:
                if quantity > 0:
                    cost_basis -= (cost_basis / quantity) * transaction.quantity
                quantity -= transaction.quantity

        if quantity == 0:
            continue
        if quantity < 0:
            errors.append(
                f"Position in {isin} went negative — likely a gap in transaction "
                "history before the earliest imported transaction"
            )
            continue

        latest = ordered[-1]
        positions.append(
            Position(
                broker="bossa",
                account_type=account_type,
                instrument_name=latest.instrument_name,
                isin=isin,
                symbol=None,
                # ASSUMPTION: Bossa's transaction history has no instrument-type
                # column (unlike XTB's "Category"), so asset class can't be
                # derived from the file the way importer.py does for XTB.
                # "other" is the same safe fallback importer.py uses for any
                # XTB category it doesn't recognize.
                asset_class="other",
                quantity=quantity,
                avg_cost=cost_basis / quantity,
                cost_currency=latest.currency,
                market_value=None,
                market_currency=None,
                valuation_date=valuation_date,
            )
        )
    return positions, errors


def attach_current_market_values(positions: list[Position]) -> list[Position]:
    """Bossa's ledger only carries historical execution prices, never a
    current value — unlike XTB, whose export states market_value directly.
    Best-effort only: a position without a resolved ticker, or without price
    history, keeps market_value=None rather than guessing."""
    updated = []
    for position in positions:
        ticker = position.ticker or position.symbol
        history = fetch_price_history(ticker) if ticker else None
        if history is not None:
            # The most recent trading day can come back as NaN before Yahoo
            # finalizes it -- drop it rather than silently write
            # market_value = NaN * quantity (issue #193, same class of bug
            # already fixed for price_change_ratio in #192).
            history = history.dropna()
        if history is None or history.empty:
            updated.append(position)
            continue
        latest_price = Decimal(str(history.iloc[-1]))
        updated.append(
            position.model_copy(
                update={
                    "market_value": latest_price * position.quantity,
                    "market_currency": position.cost_currency,
                }
            )
        )
    return updated


def dedup_key(transaction: BossaTransaction) -> str:
    """Stable identity for one transaction row, for a caller that persists
    transactions across multiple imports over time (portfolio-webapp's
    02-spec.md REQ-021) and needs to ignore rows it has already seen. Bossa's
    export has no transaction ID column, so the key is a hash of the full
    row — P1 itself has no persistence layer and does not use this."""
    canonical = json.dumps(transaction.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def date_range(transactions: list[BossaTransaction]) -> tuple[date, date] | None:
    """Min/max transaction date in one imported file — for a caller to show
    the owner, so they can check for gaps against a previous import
    (portfolio-webapp's 02-spec.md REQ-022). Code cannot detect a gap by
    itself; this only gives a human something to check."""
    if not transactions:
        return None
    dates = [t.executed_at.date() for t in transactions]
    return min(dates), max(dates)


def _parse_pl_decimal(text: str) -> Decimal:
    cleaned = text.strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    return Decimal(cleaned)
