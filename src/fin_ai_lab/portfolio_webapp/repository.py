import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import duckdb

from fin_ai_lab.portfolio_webapp.aggregators import Aggregator
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
        "INSERT INTO positions VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
    connection.execute(
        "UPDATE positions SET instrument_name = ?, isin = ?, symbol = ?, asset_class = ?, "
        "quantity = ?, avg_cost = ?, cost_currency = ?, market_value = ?, market_currency = ?, "
        "resolution_status = ?, figi = ?, ticker = ?, exchange_code = ?, identification_rule = ?, "
        "quote_currency = ? "
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
    connection.execute("DELETE FROM positions WHERE id = ?", [position_id])


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
    actually new."""
    existing = {
        row[0]
        for row in connection.execute(
            "SELECT dedup_hash FROM transactions WHERE portfolio_id = ?", [portfolio_id]
        ).fetchall()
    }
    new: list[BossaTransaction] = []
    for transaction in transactions:
        dedup_hash = dedup_key(transaction)
        if dedup_hash in existing:
            continue
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
