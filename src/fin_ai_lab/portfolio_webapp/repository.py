import hashlib
import uuid
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal

import duckdb

from fin_ai_lab.portfolio_webapp.aggregators import Aggregator, instrument_key
from fin_ai_lab.portfolio_webapp.breakdowns import Breakdown, Group
from fin_ai_lab.portfolio_webapp.cash_operations import CashOperation
from fin_ai_lab.portfolio_webapp.closed_lots import ClosedLot
from fin_ai_lab.portfolio_webapp.instrument_overrides import InstrumentOverride
from fin_ai_lab.portfolio_webapp.instruments import Decision, pair
from fin_ai_lab.portfolio_webapp.lots import OpenLot
from fin_ai_lab.portfolio_webapp.manual_valuations import ManualValuation
from fin_ai_lab.portfolio_webapp.traded_instruments import InstrumentListing
from fin_ai_lab.portfolio_xray.canonical import Position
from fin_ai_lab.portfolio_xray.ledger import BossaTransaction, dedup_key

MANUAL_BROKER = "manual"

PortfolioRow = tuple[uuid.UUID, str, str | None, str | None, datetime]
SnapshotRow = tuple[uuid.UUID, uuid.UUID, str, date, datetime, date | None, date | None]
PositionRow = tuple[
    uuid.UUID,  # id
    uuid.UUID,  # snapshot_id
    str,  # broker
    str,  # account_type
    str,  # instrument_name
    str | None,  # isin
    str | None,  # symbol
    str,  # asset_class
    object,  # quantity (Decimal)
    object | None,  # avg_cost (Decimal)
    str | None,  # cost_currency
    object | None,  # market_value (Decimal)
    str | None,  # market_currency
    date,  # valuation_date
    str,  # resolution_status
    str | None,  # figi
    str | None,  # ticker
    str | None,  # exchange_code
    str | None,  # identification_rule
    str | None,  # quote_currency
]
ReportRow = tuple[uuid.UUID, uuid.UUID, datetime, str, Decimal, str]
CommitteeJobRow = tuple[
    uuid.UUID,  # id
    uuid.UUID,  # portfolio_id
    uuid.UUID,  # snapshot_id
    str,  # variant
    str,  # status
    datetime,  # created_at
    datetime | None,  # finished_at
    str,  # model
    Decimal | None,  # cost_usd
    str | None,  # error
    str | None,  # result_json
]


def row_to_position(row: PositionRow) -> Position:
    (
        _id,
        _snapshot_id,
        broker,
        account_type,
        instrument_name,
        isin,
        symbol,
        asset_class,
        quantity,
        avg_cost,
        cost_currency,
        market_value,
        market_currency,
        valuation_date,
        resolution_status,
        figi,
        ticker,
        exchange_code,
        identification_rule,
        quote_currency,
    ) = row
    return Position(
        broker=broker,
        account_type=account_type,
        instrument_name=instrument_name,
        isin=isin,
        symbol=symbol,
        asset_class=asset_class,
        quantity=quantity,
        avg_cost=avg_cost,
        cost_currency=cost_currency,
        market_value=market_value,
        market_currency=market_currency,
        valuation_date=valuation_date,
        resolution_status=resolution_status,
        figi=figi,
        ticker=ticker,
        exchange_code=exchange_code,
        identification_rule=identification_rule,
        quote_currency=quote_currency,
    )


def position_key(row: PositionRow) -> str:
    """The per-broker instrument key of a stored position (REQ-065). A manual
    entry gets its own key per row: it is the owner's own figure and never
    merges with (or re-prices) an imported instrument by itself."""
    if row[2] == MANUAL_BROKER:
        return f"manual:{row[0]}"
    return instrument_key(row_to_position(row))


def list_portfolios(connection: duckdb.DuckDBPyConnection) -> list[PortfolioRow]:
    return connection.execute(
        "SELECT id, name, broker, account_type, created_at FROM portfolios ORDER BY created_at"
    ).fetchall()


def get_portfolio(
    connection: duckdb.DuckDBPyConnection, portfolio_id: uuid.UUID
) -> PortfolioRow | None:
    rows = connection.execute(
        "SELECT id, name, broker, account_type, created_at FROM portfolios WHERE id = ?",
        [portfolio_id],
    ).fetchall()
    return rows[0] if rows else None


def create_portfolio(
    connection: duckdb.DuckDBPyConnection,
    *,
    name: str,
    broker: str | None,
    account_type: str | None,
) -> PortfolioRow:
    portfolio_id = uuid.uuid4()
    created_at = datetime.now(UTC)
    connection.execute(
        "INSERT INTO portfolios VALUES (?, ?, ?, ?, ?)",
        [portfolio_id, name, broker, account_type, created_at],
    )
    return (portfolio_id, name, broker, account_type, created_at)


def delete_portfolio(connection: duckdb.DuckDBPyConnection, portfolio_id: uuid.UUID) -> None:
    """Removes a portfolio and everything that hangs off it. The schema has no
    foreign keys, so the cascade is explicit -- and one transaction, so a
    failure halfway never leaves orphaned positions behind. Breakdown
    assignments and instrument decisions are keyed by instrument, not by
    portfolio (another portfolio may hold the same asset), so they stay."""
    snapshot_ids = "SELECT id FROM portfolio_snapshots WHERE portfolio_id = ?"
    position_ids = f"SELECT id FROM positions WHERE snapshot_id IN ({snapshot_ids})"
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute(
            f"DELETE FROM position_lots WHERE position_id IN ({position_ids})", [portfolio_id]
        )
        connection.execute(
            f"DELETE FROM manual_valuations WHERE position_id IN ({position_ids})", [portfolio_id]
        )
        connection.execute(
            f"DELETE FROM positions WHERE snapshot_id IN ({snapshot_ids})", [portfolio_id]
        )
        connection.execute(
            f"DELETE FROM reports WHERE snapshot_id IN ({snapshot_ids})", [portfolio_id]
        )
        for table in (
            "committee_jobs",
            "aggregators",
            "transactions",
            "cash_operations",
            "closed_lots",
            "portfolio_snapshots",
        ):
            connection.execute(f"DELETE FROM {table} WHERE portfolio_id = ?", [portfolio_id])
        connection.execute("DELETE FROM portfolios WHERE id = ?", [portfolio_id])
    except Exception:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def create_snapshot(
    connection: duckdb.DuckDBPyConnection,
    *,
    portfolio_id: uuid.UUID,
    broker: str,
    valuation_date: date,
    source_file_date_min: date | None = None,
    source_file_date_max: date | None = None,
) -> SnapshotRow:
    snapshot_id = uuid.uuid4()
    imported_at = datetime.now(UTC)
    connection.execute(
        "INSERT INTO portfolio_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            snapshot_id,
            portfolio_id,
            broker,
            valuation_date,
            imported_at,
            source_file_date_min,
            source_file_date_max,
        ],
    )
    return (
        snapshot_id,
        portfolio_id,
        broker,
        valuation_date,
        imported_at,
        source_file_date_min,
        source_file_date_max,
    )


def insert_positions(
    connection: duckdb.DuckDBPyConnection, *, snapshot_id: uuid.UUID, positions: list[Position]
) -> None:
    for position in positions:
        connection.execute(
            "INSERT INTO positions VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                uuid.uuid4(),
                snapshot_id,
                position.broker,
                position.account_type,
                position.instrument_name,
                position.isin,
                position.symbol,
                position.asset_class,
                position.quantity,
                position.avg_cost,
                position.cost_currency,
                position.market_value,
                position.market_currency,
                position.valuation_date,
                position.resolution_status,
                position.figi,
                position.ticker,
                position.exchange_code,
                position.identification_rule,
                position.quote_currency,
            ],
        )


def insert_position(
    connection: duckdb.DuckDBPyConnection, *, snapshot_id: uuid.UUID, position: Position
) -> PositionRow:
    position_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO positions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            position_id,
            snapshot_id,
            position.broker,
            position.account_type,
            position.instrument_name,
            position.isin,
            position.symbol,
            position.asset_class,
            position.quantity,
            position.avg_cost,
            position.cost_currency,
            position.market_value,
            position.market_currency,
            position.valuation_date,
            position.resolution_status,
            position.figi,
            position.ticker,
            position.exchange_code,
            position.identification_rule,
            position.quote_currency,
        ],
    )
    row = get_position(connection, position_id)
    assert row is not None
    return row


def get_position(
    connection: duckdb.DuckDBPyConnection, position_id: uuid.UUID
) -> PositionRow | None:
    rows = connection.execute(
        "SELECT id, snapshot_id, broker, account_type, instrument_name, isin, symbol, "
        "asset_class, quantity, avg_cost, cost_currency, market_value, market_currency, "
        "valuation_date, resolution_status, figi, ticker, exchange_code, identification_rule, "
        "quote_currency "
        "FROM positions WHERE id = ?",
        [position_id],
    ).fetchall()
    return rows[0] if rows else None


def update_position(
    connection: duckdb.DuckDBPyConnection, *, position_id: uuid.UUID, position: Position
) -> PositionRow:
    # Only manual positions are ever updated (REQ-011); their valuation_date
    # is the purchase date the owner can correct (#288).
    connection.execute(
        "UPDATE positions SET instrument_name = ?, isin = ?, symbol = ?, asset_class = ?, "
        "quantity = ?, avg_cost = ?, cost_currency = ?, market_value = ?, market_currency = ?, "
        "valuation_date = ?, resolution_status = ?, figi = ?, ticker = ?, exchange_code = ?, "
        "identification_rule = ?, quote_currency = ? "
        "WHERE id = ?",
        [
            position.instrument_name,
            position.isin,
            position.symbol,
            position.asset_class,
            position.quantity,
            position.avg_cost,
            position.cost_currency,
            position.market_value,
            position.market_currency,
            position.valuation_date,
            position.resolution_status,
            position.figi,
            position.ticker,
            position.exchange_code,
            position.identification_rule,
            position.quote_currency,
            position_id,
        ],
    )
    row = get_position(connection, position_id)
    assert row is not None
    return row


def delete_position(connection: duckdb.DuckDBPyConnection, position_id: uuid.UUID) -> None:
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute("DELETE FROM manual_valuations WHERE position_id = ?", [position_id])
        connection.execute("DELETE FROM positions WHERE id = ?", [position_id])
    except Exception:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def set_market_value(
    connection: duckdb.DuckDBPyConnection, position_id: uuid.UUID, market_value: Decimal
) -> None:
    connection.execute(
        "UPDATE positions SET market_value = ? WHERE id = ?", [market_value, position_id]
    )


def list_manual_valuations(
    connection: duckdb.DuckDBPyConnection, position_id: uuid.UUID
) -> list[ManualValuation]:
    rows = connection.execute(
        "SELECT valued_on, unit_value FROM manual_valuations WHERE position_id = ? "
        "ORDER BY valued_on",
        [position_id],
    ).fetchall()
    return [ManualValuation(valued_on=valued_on, unit_value=value) for valued_on, value in rows]


def save_manual_valuation(
    connection: duckdb.DuckDBPyConnection, position_id: uuid.UUID, valuation: ManualValuation
) -> None:
    connection.execute(
        "INSERT INTO manual_valuations (position_id, valued_on, unit_value, recorded_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT (position_id, valued_on) DO UPDATE SET unit_value = excluded.unit_value, "
        "recorded_at = excluded.recorded_at",
        [position_id, valuation.valued_on, valuation.unit_value, datetime.now(UTC)],
    )


def delete_manual_valuation(
    connection: duckdb.DuckDBPyConnection, position_id: uuid.UUID, valued_on: date
) -> None:
    connection.execute(
        "DELETE FROM manual_valuations WHERE position_id = ? AND valued_on = ?",
        [position_id, valued_on],
    )


def list_snapshots(
    connection: duckdb.DuckDBPyConnection, portfolio_id: uuid.UUID
) -> list[SnapshotRow]:
    # The manual-positions container (broker == MANUAL_BROKER, see
    # get_or_create_manual_snapshot) is not a point-in-time import -- it
    # would otherwise become "the latest snapshot" the moment someone adds a
    # manual position after their last real import, hiding it from view.
    return connection.execute(
        "SELECT id, portfolio_id, broker, valuation_date, imported_at, "
        "source_file_date_min, source_file_date_max FROM portfolio_snapshots "
        "WHERE portfolio_id = ? AND broker != ? ORDER BY imported_at DESC",
        [portfolio_id, MANUAL_BROKER],
    ).fetchall()


def find_manual_snapshot(
    connection: duckdb.DuckDBPyConnection, portfolio_id: uuid.UUID
) -> SnapshotRow | None:
    rows = connection.execute(
        "SELECT id, portfolio_id, broker, valuation_date, imported_at, "
        "source_file_date_min, source_file_date_max FROM portfolio_snapshots "
        "WHERE portfolio_id = ? AND broker = ?",
        [portfolio_id, MANUAL_BROKER],
    ).fetchall()
    return rows[0] if rows else None


def get_or_create_manual_snapshot(
    connection: duckdb.DuckDBPyConnection, portfolio_id: uuid.UUID
) -> SnapshotRow:
    existing = find_manual_snapshot(connection, portfolio_id)
    if existing is not None:
        return existing
    return create_snapshot(
        connection,
        portfolio_id=portfolio_id,
        broker=MANUAL_BROKER,
        valuation_date=date.today(),
    )


def list_positions(
    connection: duckdb.DuckDBPyConnection, snapshot_id: uuid.UUID
) -> list[PositionRow]:
    return connection.execute(
        "SELECT id, snapshot_id, broker, account_type, instrument_name, isin, symbol, "
        "asset_class, quantity, avg_cost, cost_currency, market_value, market_currency, "
        "valuation_date, resolution_status, figi, ticker, exchange_code, identification_rule, "
        "quote_currency "
        "FROM positions WHERE snapshot_id = ?",
        [snapshot_id],
    ).fetchall()


def insert_lots(
    connection: duckdb.DuckDBPyConnection, *, position_id: uuid.UUID, lots: list[OpenLot]
) -> None:
    for lot in lots:
        connection.execute(
            "INSERT INTO position_lots (position_id, lot_ref, quantity, opened_on) "
            "VALUES (?, ?, ?, ?)",
            [position_id, lot.lot_ref, lot.quantity, lot.opened_on],
        )


def list_lots(
    connection: duckdb.DuckDBPyConnection, position_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[Decimal, date]]]:
    """(quantity, opened_on) per lot, grouped by position -- positions with
    no stored lots are simply absent from the result."""
    if not position_ids:
        return {}
    placeholders = ", ".join("?" for _ in position_ids)
    rows = connection.execute(
        "SELECT position_id, quantity, opened_on FROM position_lots "
        f"WHERE position_id IN ({placeholders}) ORDER BY opened_on",
        position_ids,
    ).fetchall()
    lots: dict[uuid.UUID, list[tuple[Decimal, date]]] = {}
    for position_id, quantity, opened_on in rows:
        lots.setdefault(position_id, []).append((quantity, opened_on))
    return lots


def find_latest_report(
    connection: duckdb.DuckDBPyConnection, snapshot_id: uuid.UUID
) -> ReportRow | None:
    rows = connection.execute(
        "SELECT id, snapshot_id, generated_at, model, cost_usd, content_md "
        "FROM reports WHERE snapshot_id = ? ORDER BY generated_at DESC LIMIT 1",
        [snapshot_id],
    ).fetchall()
    return rows[0] if rows else None


def create_report(
    connection: duckdb.DuckDBPyConnection,
    *,
    snapshot_id: uuid.UUID,
    model: str,
    cost_usd: Decimal,
    content_md: str,
) -> ReportRow:
    report_id = uuid.uuid4()
    generated_at = datetime.now(UTC)
    connection.execute(
        "INSERT INTO reports VALUES (?, ?, ?, ?, ?, ?)",
        [report_id, snapshot_id, generated_at, model, cost_usd, content_md],
    )
    return (report_id, snapshot_id, generated_at, model, cost_usd, content_md)


def create_committee_job(
    connection: duckdb.DuckDBPyConnection,
    *,
    portfolio_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    variant: str,
    model: str,
) -> CommitteeJobRow:
    job_id = uuid.uuid4()
    created_at = datetime.now(UTC)
    connection.execute(
        "INSERT INTO committee_jobs "
        "(id, portfolio_id, snapshot_id, variant, status, created_at, model) "
        "VALUES (?, ?, ?, ?, 'pending', ?, ?)",
        [job_id, portfolio_id, snapshot_id, variant, created_at, model],
    )
    return (
        job_id,
        portfolio_id,
        snapshot_id,
        variant,
        "pending",
        created_at,
        None,
        model,
        None,
        None,
        None,
    )


def get_committee_job(
    connection: duckdb.DuckDBPyConnection, job_id: uuid.UUID
) -> CommitteeJobRow | None:
    rows = connection.execute(
        "SELECT id, portfolio_id, snapshot_id, variant, status, created_at, finished_at, "
        "model, cost_usd, error, result_json FROM committee_jobs WHERE id = ?",
        [job_id],
    ).fetchall()
    return rows[0] if rows else None


def find_latest_done_committee_job(
    connection: duckdb.DuckDBPyConnection, snapshot_id: uuid.UUID, variant: str
) -> CommitteeJobRow | None:
    rows = connection.execute(
        "SELECT id, portfolio_id, snapshot_id, variant, status, created_at, finished_at, "
        "model, cost_usd, error, result_json FROM committee_jobs "
        "WHERE snapshot_id = ? AND variant = ? AND status = 'done' "
        "ORDER BY created_at DESC LIMIT 1",
        [snapshot_id, variant],
    ).fetchall()
    return rows[0] if rows else None


def update_committee_job_status(
    connection: duckdb.DuckDBPyConnection, job_id: uuid.UUID, status: str
) -> None:
    connection.execute("UPDATE committee_jobs SET status = ? WHERE id = ?", [status, job_id])


def finish_committee_job(
    connection: duckdb.DuckDBPyConnection,
    job_id: uuid.UUID,
    *,
    status: str,
    cost_usd: Decimal | None = None,
    error: str | None = None,
    result_json: str | None = None,
) -> None:
    connection.execute(
        "UPDATE committee_jobs SET status = ?, finished_at = ?, cost_usd = ?, error = ?, "
        "result_json = ? WHERE id = ?",
        [status, datetime.now(UTC), cost_usd, error, result_json, job_id],
    )


# Trades read from a Bossa financial history (fin-ai-lab#246) carry no time
# of day, so their dedup_hash is not the full-row hash of a `hisPW` line.
FINANCIAL_HASH_PREFIX = "fin:"


def trade_key(transaction: BossaTransaction) -> tuple:
    """What two listings of the same trade agree on, whichever export they
    came from: hisPW has the time of day, the financial history does not."""
    return (
        transaction.executed_at.date(),
        transaction.isin,
        transaction.side,
        transaction.quantity,
        transaction.net_value,
        transaction.currency,
    )


def _stored_trade_keys(
    connection: duckdb.DuckDBPyConnection, portfolio_id: uuid.UUID, *, financial_only: bool
) -> Counter:
    """Multiset of the stored trades' keys -- two identical fills on one day
    are two entries."""
    rows = connection.execute(
        "SELECT dedup_hash, executed_at, isin, side, quantity, net_value, currency "
        "FROM transactions WHERE portfolio_id = ?",
        [portfolio_id],
    ).fetchall()
    return Counter(
        (row[1].date(), row[2], row[3], row[4], row[5], row[6])
        for row in rows
        if not financial_only or row[0].startswith(FINANCIAL_HASH_PREFIX)
    )


def _insert_transaction(
    connection: duckdb.DuckDBPyConnection,
    *,
    dedup_hash: str,
    portfolio_id: uuid.UUID,
    broker: str,
    transaction: BossaTransaction,
) -> None:
    # Named columns, not positional VALUES: instrument_name/value/net_value
    # were added to this table by ALTER TABLE (db.py MIGRATIONS), which
    # appends physically at the end regardless of where they're listed in
    # SCHEMA's own CREATE TABLE -- a database migrated through that path
    # has a different physical column order than a freshly created one,
    # and positional VALUES silently mismatched them (reproduced live).
    connection.execute(
        "INSERT INTO transactions "
        "(dedup_hash, portfolio_id, broker, executed_at, instrument_name, isin, side, "
        "quantity, price, value, commission, net_value, currency) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            dedup_hash,
            portfolio_id,
            broker,
            transaction.executed_at,
            transaction.instrument_name,
            transaction.isin,
            transaction.side,
            transaction.quantity,
            transaction.price,
            transaction.value,
            transaction.commission,
            transaction.net_value,
            transaction.currency,
        ],
    )


def insert_transactions(
    connection: duckdb.DuckDBPyConnection,
    *,
    portfolio_id: uuid.UUID,
    broker: str,
    transactions: list[BossaTransaction],
) -> list[BossaTransaction]:
    """Persists only transactions not already stored for this portfolio
    (ledger.dedup_key identity, 02-spec.md REQ-021) and returns just the
    newly-inserted ones, so the caller can report how much of the file was
    actually new. A trade already stored from a financial history (same
    date, ISIN, side, quantity, net amount and currency) is the same trade,
    not a new one."""
    existing = {
        row[0]
        for row in connection.execute(
            "SELECT dedup_hash FROM transactions WHERE portfolio_id = ?", [portfolio_id]
        ).fetchall()
    }
    from_financial_history = _stored_trade_keys(connection, portfolio_id, financial_only=True)
    new: list[BossaTransaction] = []
    for transaction in transactions:
        dedup_hash = dedup_key(transaction)
        if dedup_hash in existing:
            continue
        key = trade_key(transaction)
        if from_financial_history[key] > 0:
            from_financial_history[key] -= 1
            continue
        _insert_transaction(
            connection,
            dedup_hash=dedup_hash,
            portfolio_id=portfolio_id,
            broker=broker,
            transaction=transaction,
        )
        existing.add(dedup_hash)
        new.append(transaction)
    return new


def insert_financial_history_trades(
    connection: duckdb.DuckDBPyConnection,
    *,
    portfolio_id: uuid.UUID,
    broker: str,
    transactions: list[BossaTransaction],
) -> list[BossaTransaction]:
    """Like insert_transactions, for trades read from a Bossa financial
    history: a trade already stored -- from `hisPW` or from an earlier
    financial-history export -- is skipped, one stored entry cancelling one
    incoming entry, so identical fills on one day are kept and an
    overlapping export adds nothing twice."""
    existing = {
        row[0]
        for row in connection.execute(
            "SELECT dedup_hash FROM transactions WHERE portfolio_id = ?", [portfolio_id]
        ).fetchall()
    }
    stored = _stored_trade_keys(connection, portfolio_id, financial_only=False)
    new: list[BossaTransaction] = []
    for transaction in transactions:
        key = trade_key(transaction)
        if stored[key] > 0:
            stored[key] -= 1
            continue
        # The primary key is (portfolio_id, dedup_hash) since #247, so the
        # portfolio in the hash is no longer needed; it stays so the hashes
        # of rows stored before that keep their format.
        digest = hashlib.sha256(f"{portfolio_id}|{key!r}".encode()).hexdigest()[:24]
        occurrence = 0
        while f"{FINANCIAL_HASH_PREFIX}{digest}:{occurrence}" in existing:
            occurrence += 1
        dedup_hash = f"{FINANCIAL_HASH_PREFIX}{digest}:{occurrence}"
        _insert_transaction(
            connection,
            dedup_hash=dedup_hash,
            portfolio_id=portfolio_id,
            broker=broker,
            transaction=transaction,
        )
        existing.add(dedup_hash)
        new.append(transaction)
    return new


def list_transactions(
    connection: duckdb.DuckDBPyConnection, portfolio_id: uuid.UUID
) -> list[BossaTransaction]:
    rows = connection.execute(
        "SELECT executed_at, instrument_name, isin, side, quantity, price, value, "
        "commission, net_value, currency FROM transactions WHERE portfolio_id = ? "
        "ORDER BY executed_at",
        [portfolio_id],
    ).fetchall()
    return [
        BossaTransaction(
            executed_at=row[0],
            instrument_name=row[1],
            isin=row[2],
            side=row[3],
            quantity=row[4],
            price=row[5],
            value=row[6],
            commission=row[7],
            net_value=row[8],
            currency=row[9],
        )
        for row in rows
    ]


def insert_cash_operations(
    connection: duckdb.DuckDBPyConnection,
    *,
    portfolio_id: uuid.UUID,
    operations: list[CashOperation],
) -> int:
    """Stores only operations whose XTB ID this portfolio does not have yet
    (a later, overlapping export re-lists the old ones) and returns how many
    were new. An operation stored before its ticker and comment were read
    (#265) gets them filled in from the re-listed row."""
    rows = connection.execute(
        "SELECT op_id, ticker IS NULL AND comment IS NULL FROM cash_operations "
        "WHERE portfolio_id = ?",
        [portfolio_id],
    ).fetchall()
    existing = {row[0] for row in rows}
    missing_details = {row[0] for row in rows if row[1]}
    added = 0
    for operation in operations:
        if operation.op_id in existing:
            if operation.op_id in missing_details and (operation.ticker or operation.comment):
                connection.execute(
                    "UPDATE cash_operations SET ticker = ?, comment = ? "
                    "WHERE portfolio_id = ? AND op_id = ?",
                    [operation.ticker, operation.comment, portfolio_id, operation.op_id],
                )
                missing_details.discard(operation.op_id)
            continue
        connection.execute(
            "INSERT INTO cash_operations (portfolio_id, op_id, kind, op_type, instrument, "
            "occurred_at, amount, currency, ticker, comment) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                portfolio_id,
                operation.op_id,
                operation.kind,
                operation.op_type,
                operation.instrument,
                operation.occurred_at,
                operation.amount,
                operation.currency,
                operation.ticker,
                operation.comment,
            ],
        )
        existing.add(operation.op_id)
        added += 1
    return added


def list_cash_operations(
    connection: duckdb.DuckDBPyConnection, portfolio_id: uuid.UUID
) -> list[CashOperation]:
    rows = connection.execute(
        "SELECT op_id, kind, op_type, instrument, occurred_at, amount, currency, ticker, comment "
        "FROM cash_operations WHERE portfolio_id = ? ORDER BY occurred_at",
        [portfolio_id],
    ).fetchall()
    return [
        CashOperation(
            op_id=row[0],
            kind=row[1],
            op_type=row[2],
            instrument=row[3],
            occurred_at=row[4],
            amount=row[5],
            currency=row[6],
            ticker=row[7],
            comment=row[8],
        )
        for row in rows
    ]


def insert_closed_lots(
    connection: duckdb.DuckDBPyConnection, *, portfolio_id: uuid.UUID, lots: list[ClosedLot]
) -> int:
    """Stores only lots this portfolio does not have yet (a later, overlapping
    export re-lists the old ones) and returns how many were new."""
    existing = {
        row[0]
        for row in connection.execute(
            "SELECT lot_id FROM closed_lots WHERE portfolio_id = ?", [portfolio_id]
        ).fetchall()
    }
    added = 0
    for lot in lots:
        if lot.lot_id in existing:
            continue
        connection.execute(
            "INSERT INTO closed_lots (portfolio_id, lot_id, ticker, instrument, volume, "
            "open_price, opened_at, closed_at, purchase_value, sale_value, currency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                portfolio_id,
                lot.lot_id,
                lot.ticker,
                lot.instrument,
                lot.volume,
                lot.open_price,
                lot.opened_at,
                lot.closed_at,
                lot.purchase_value,
                lot.sale_value,
                lot.currency,
            ],
        )
        existing.add(lot.lot_id)
        added += 1
    return added


def list_closed_lots(
    connection: duckdb.DuckDBPyConnection, portfolio_id: uuid.UUID
) -> list[ClosedLot]:
    rows = connection.execute(
        "SELECT lot_id, ticker, instrument, volume, open_price, opened_at, closed_at, "
        "purchase_value, sale_value, currency FROM closed_lots "
        "WHERE portfolio_id = ? ORDER BY closed_at",
        [portfolio_id],
    ).fetchall()
    return [ClosedLot(*row) for row in rows]


def _row_to_aggregator(row: tuple) -> Aggregator:
    id_, portfolio_id, name, member_instrument_keys, member_aggregator_ids = row
    return Aggregator(
        id=id_,
        portfolio_id=portfolio_id,
        name=name,
        member_instrument_keys=list(member_instrument_keys or []),
        member_aggregator_ids=list(member_aggregator_ids or []),
    )


def create_aggregator(
    connection: duckdb.DuckDBPyConnection,
    *,
    portfolio_id: uuid.UUID,
    name: str,
    member_instrument_keys: list[str],
    member_aggregator_ids: list[uuid.UUID],
) -> Aggregator:
    aggregator_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO aggregators VALUES (?, ?, ?, ?, ?)",
        [aggregator_id, portfolio_id, name, member_instrument_keys, member_aggregator_ids],
    )
    row = get_aggregator(connection, aggregator_id)
    assert row is not None
    return row


def get_aggregator(
    connection: duckdb.DuckDBPyConnection, aggregator_id: uuid.UUID
) -> Aggregator | None:
    rows = connection.execute(
        "SELECT id, portfolio_id, name, member_instrument_keys, member_aggregator_ids "
        "FROM aggregators WHERE id = ?",
        [aggregator_id],
    ).fetchall()
    return _row_to_aggregator(rows[0]) if rows else None


def list_aggregators(
    connection: duckdb.DuckDBPyConnection, portfolio_id: uuid.UUID
) -> list[Aggregator]:
    rows = connection.execute(
        "SELECT id, portfolio_id, name, member_instrument_keys, member_aggregator_ids "
        "FROM aggregators WHERE portfolio_id = ?",
        [portfolio_id],
    ).fetchall()
    return [_row_to_aggregator(row) for row in rows]


def update_aggregator(
    connection: duckdb.DuckDBPyConnection,
    *,
    aggregator_id: uuid.UUID,
    name: str,
    member_instrument_keys: list[str],
    member_aggregator_ids: list[uuid.UUID],
) -> Aggregator:
    connection.execute(
        "UPDATE aggregators SET name = ?, member_instrument_keys = ?, "
        "member_aggregator_ids = ? WHERE id = ?",
        [name, member_instrument_keys, member_aggregator_ids, aggregator_id],
    )
    row = get_aggregator(connection, aggregator_id)
    assert row is not None
    return row


def delete_aggregator(connection: duckdb.DuckDBPyConnection, aggregator_id: uuid.UUID) -> None:
    # REQ-064: deleting an aggregator that is itself a member of another one
    # must not leave a dangling reference in that other aggregator's
    # member_aggregator_ids -- read-modify-write in Python rather than SQL
    # array surgery, same "small and explicit" style as the rest of this
    # module.
    target = get_aggregator(connection, aggregator_id)
    if target is not None:
        for other in list_aggregators(connection, target.portfolio_id):
            if aggregator_id in other.member_aggregator_ids:
                update_aggregator(
                    connection,
                    aggregator_id=other.id,
                    name=other.name,
                    member_instrument_keys=other.member_instrument_keys,
                    member_aggregator_ids=[
                        m for m in other.member_aggregator_ids if m != aggregator_id
                    ],
                )
    connection.execute("DELETE FROM aggregators WHERE id = ?", [aggregator_id])


def list_breakdowns(connection: duckdb.DuckDBPyConnection) -> list[Breakdown]:
    rows = connection.execute(
        "SELECT id, name, is_default FROM breakdowns ORDER BY created_at"
    ).fetchall()
    return [_load_breakdown(connection, row) for row in rows]


def get_breakdown(
    connection: duckdb.DuckDBPyConnection, breakdown_id: uuid.UUID
) -> Breakdown | None:
    rows = connection.execute(
        "SELECT id, name, is_default FROM breakdowns WHERE id = ?", [breakdown_id]
    ).fetchall()
    return _load_breakdown(connection, rows[0]) if rows else None


def create_breakdown(connection: duckdb.DuckDBPyConnection, *, name: str) -> Breakdown:
    breakdown_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO breakdowns (id, name, is_default, created_at) VALUES (?, ?, false, ?)",
        [breakdown_id, name, datetime.now(UTC)],
    )
    return Breakdown(id=breakdown_id, name=name, is_default=False, groups=[], assignments={})


def update_breakdown(
    connection: duckdb.DuckDBPyConnection,
    *,
    breakdown_id: uuid.UUID,
    name: str,
    is_default: bool,
) -> Breakdown:
    # REQ-080: at most one default -- setting it here clears it everywhere else.
    if is_default:
        connection.execute("UPDATE breakdowns SET is_default = false WHERE id != ?", [breakdown_id])
    connection.execute(
        "UPDATE breakdowns SET name = ?, is_default = ? WHERE id = ?",
        [name, is_default, breakdown_id],
    )
    breakdown = get_breakdown(connection, breakdown_id)
    assert breakdown is not None
    return breakdown


def delete_breakdown(connection: duckdb.DuckDBPyConnection, breakdown_id: uuid.UUID) -> None:
    connection.execute("DELETE FROM breakdown_assignments WHERE breakdown_id = ?", [breakdown_id])
    connection.execute("DELETE FROM breakdown_groups WHERE breakdown_id = ?", [breakdown_id])
    connection.execute("DELETE FROM breakdowns WHERE id = ?", [breakdown_id])


def duplicate_breakdown(
    connection: duckdb.DuckDBPyConnection, source: Breakdown, *, name: str
) -> Breakdown:
    copy = create_breakdown(connection, name=name)
    new_ids = {group.id: uuid.uuid4() for group in source.groups}
    for group in source.groups:
        connection.execute(
            "INSERT INTO breakdown_groups (id, breakdown_id, parent_id, name, position) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                new_ids[group.id],
                copy.id,
                new_ids.get(group.parent_id) if group.parent_id is not None else None,
                group.name,
                group.position,
            ],
        )
    for key, group_id in source.assignments.items():
        set_assignment(
            connection,
            breakdown_id=copy.id,
            instrument_key=key,
            group_id=new_ids[group_id],
        )
    duplicated = get_breakdown(connection, copy.id)
    assert duplicated is not None
    return duplicated


def create_breakdown_group(
    connection: duckdb.DuckDBPyConnection,
    *,
    breakdown_id: uuid.UUID,
    name: str,
    parent_id: uuid.UUID | None,
) -> uuid.UUID:
    # Appended after its siblings -- creation order is the display (and chart
    # colour) order until the owner reorders.
    (next_position,) = connection.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM breakdown_groups WHERE breakdown_id = ?",
        [breakdown_id],
    ).fetchone()
    group_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO breakdown_groups (id, breakdown_id, parent_id, name, position) "
        "VALUES (?, ?, ?, ?, ?)",
        [group_id, breakdown_id, parent_id, name, next_position],
    )
    return group_id


def update_breakdown_group(
    connection: duckdb.DuckDBPyConnection,
    *,
    group_id: uuid.UUID,
    name: str,
    parent_id: uuid.UUID | None,
) -> None:
    connection.execute(
        "UPDATE breakdown_groups SET name = ?, parent_id = ? WHERE id = ?",
        [name, parent_id, group_id],
    )


def delete_breakdown_group(
    connection: duckdb.DuckDBPyConnection, breakdown: Breakdown, group_id: uuid.UUID
) -> None:
    """REQ-083: subgroups and assigned instruments move up to the deleted
    group's parent; at the top level the instruments become unassigned
    ("Bez grupy") -- nothing the owner sorted disappears silently."""
    group = next(g for g in breakdown.groups if g.id == group_id)
    connection.execute(
        "UPDATE breakdown_groups SET parent_id = ? WHERE parent_id = ?",
        [group.parent_id, group_id],
    )
    if group.parent_id is None:
        connection.execute(
            "DELETE FROM breakdown_assignments WHERE breakdown_id = ? AND group_id = ?",
            [breakdown.id, group_id],
        )
    else:
        connection.execute(
            "UPDATE breakdown_assignments SET group_id = ? WHERE breakdown_id = ? AND group_id = ?",
            [group.parent_id, breakdown.id, group_id],
        )
    connection.execute("DELETE FROM breakdown_groups WHERE id = ?", [group_id])


def set_assignment(
    connection: duckdb.DuckDBPyConnection,
    *,
    breakdown_id: uuid.UUID,
    instrument_key: str,
    group_id: uuid.UUID | None,
    replaces: tuple[str, ...] = (),
) -> None:
    # `replaces`: the asset's other member keys (S12) -- the owner just set
    # the group for the whole asset, so what its members held before goes.
    for member_key in replaces:
        connection.execute(
            "DELETE FROM breakdown_assignments WHERE breakdown_id = ? AND instrument_key = ?",
            [breakdown_id, member_key],
        )
    # One row per (breakdown, instrument) -- the table's primary key -- so
    # moving an instrument replaces its group rather than adding a second.
    if group_id is None:
        connection.execute(
            "DELETE FROM breakdown_assignments WHERE breakdown_id = ? AND instrument_key = ?",
            [breakdown_id, instrument_key],
        )
        return
    connection.execute(
        "INSERT INTO breakdown_assignments (breakdown_id, instrument_key, group_id) "
        "VALUES (?, ?, ?) ON CONFLICT (breakdown_id, instrument_key) "
        "DO UPDATE SET group_id = excluded.group_id",
        [breakdown_id, instrument_key, group_id],
    )


def list_current_positions(
    connection: duckdb.DuckDBPyConnection,
) -> list[tuple[PortfolioRow, PositionRow]]:
    """What every portfolio holds now: its latest import's positions plus its
    manual ones -- the same rows the valuation view lists."""
    current = []
    for portfolio in list_portfolios(connection):
        snapshots = list_snapshots(connection, portfolio[0])
        if snapshots:
            current.extend((portfolio, row) for row in list_positions(connection, snapshots[0][0]))
        manual = find_manual_snapshot(connection, portfolio[0])
        if manual is not None:
            current.extend((portfolio, row) for row in list_positions(connection, manual[0]))
    return current


def list_instrument_decisions(connection: duckdb.DuckDBPyConnection) -> list[Decision]:
    rows = connection.execute(
        "SELECT key_a, key_b, same FROM instrument_decisions ORDER BY decided_at"
    ).fetchall()
    return [Decision(key_a=key_a, key_b=key_b, same=same) for key_a, key_b, same in rows]


def set_instrument_decision(
    connection: duckdb.DuckDBPyConnection, *, key_a: str, key_b: str, same: bool
) -> None:
    first, second = pair(key_a, key_b)
    connection.execute(
        "INSERT INTO instrument_decisions (key_a, key_b, same, decided_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (key_a, key_b) DO UPDATE SET same = excluded.same, "
        "decided_at = excluded.decided_at",
        [first, second, same, datetime.now(UTC)],
    )


def delete_same_decisions(connection: duckdb.DuckDBPyConnection, key: str) -> None:
    connection.execute(
        "DELETE FROM instrument_decisions WHERE same AND (key_a = ? OR key_b = ?)", [key, key]
    )


def list_instrument_listings(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, InstrumentListing]:
    rows = connection.execute(
        "SELECT isin, status, figi, ticker, exchange_code, identification_rule, quote_currency "
        "FROM instrument_listings"
    ).fetchall()
    return {
        row[0]: InstrumentListing(
            isin=row[0],
            status=row[1],
            figi=row[2],
            ticker=row[3],
            exchange_code=row[4],
            identification_rule=row[5],
            quote_currency=row[6],
        )
        for row in rows
    }


def save_instrument_listings(
    connection: duckdb.DuckDBPyConnection, listings: list[InstrumentListing]
) -> None:
    identified_at = datetime.now(UTC)
    for listing in listings:
        connection.execute(
            "INSERT INTO instrument_listings (isin, status, figi, ticker, exchange_code, "
            "identification_rule, quote_currency, identified_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (isin) DO UPDATE SET status = excluded.status, figi = excluded.figi, "
            "ticker = excluded.ticker, exchange_code = excluded.exchange_code, "
            "identification_rule = excluded.identification_rule, "
            "quote_currency = excluded.quote_currency, identified_at = excluded.identified_at",
            [
                listing.isin,
                listing.status,
                listing.figi,
                listing.ticker,
                listing.exchange_code,
                listing.identification_rule,
                listing.quote_currency,
                identified_at,
            ],
        )


def list_instrument_overrides(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, InstrumentOverride]:
    rows = connection.execute(
        "SELECT instrument_key, yahoo_ticker, quote_currency FROM instrument_overrides"
    ).fetchall()
    return {
        key: InstrumentOverride(key=key, yahoo_ticker=ticker, quote_currency=currency)
        for key, ticker, currency in rows
    }


def save_instrument_override(
    connection: duckdb.DuckDBPyConnection, override: InstrumentOverride
) -> None:
    connection.execute(
        "INSERT INTO instrument_overrides (instrument_key, yahoo_ticker, quote_currency, "
        "updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (instrument_key) DO UPDATE SET yahoo_ticker = excluded.yahoo_ticker, "
        "quote_currency = excluded.quote_currency, updated_at = excluded.updated_at",
        [override.key, override.yahoo_ticker, override.quote_currency, datetime.now(UTC)],
    )


def delete_instrument_override(connection: duckdb.DuckDBPyConnection, key: str) -> None:
    connection.execute("DELETE FROM instrument_overrides WHERE instrument_key = ?", [key])


def _load_breakdown(connection: duckdb.DuckDBPyConnection, row: tuple) -> Breakdown:
    breakdown_id, name, is_default = row
    groups = [
        Group(id=group_id, name=group_name, parent_id=parent_id, position=position)
        for group_id, group_name, parent_id, position in connection.execute(
            "SELECT id, name, parent_id, position FROM breakdown_groups "
            "WHERE breakdown_id = ? ORDER BY position",
            [breakdown_id],
        ).fetchall()
    ]
    assignments = dict(
        connection.execute(
            "SELECT instrument_key, group_id FROM breakdown_assignments WHERE breakdown_id = ?",
            [breakdown_id],
        ).fetchall()
    )
    return Breakdown(
        id=breakdown_id, name=name, is_default=is_default, groups=groups, assignments=assignments
    )
