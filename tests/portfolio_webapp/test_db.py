import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from fin_ai_lab.portfolio_webapp import db  # noqa: E402

FIRST_PORTFOLIO = uuid.UUID("00000000-0000-0000-0000-000000000001")
SECOND_PORTFOLIO = uuid.UUID("00000000-0000-0000-0000-000000000002")

# The transactions table as an earlier version left it: created by the S1
# skeleton with dedup_hash alone as the key, then given its last three
# columns by db.MIGRATIONS (so they sit physically at the end).
_LEGACY_TRANSACTIONS = """
CREATE TABLE transactions (
    dedup_hash TEXT PRIMARY KEY,
    portfolio_id UUID NOT NULL,
    broker TEXT NOT NULL,
    executed_at TIMESTAMP NOT NULL,
    isin TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity DECIMAL(24, 8) NOT NULL,
    price DECIMAL(24, 8) NOT NULL,
    commission DECIMAL(24, 8) NOT NULL,
    currency TEXT NOT NULL
);
ALTER TABLE transactions ADD COLUMN instrument_name TEXT;
ALTER TABLE transactions ADD COLUMN value DECIMAL(24, 8);
ALTER TABLE transactions ADD COLUMN net_value DECIMAL(24, 8);
"""

_INSERT = (
    "INSERT INTO transactions (dedup_hash, portfolio_id, broker, executed_at, "
    "instrument_name, isin, side, quantity, price, value, commission, net_value, "
    "currency) VALUES (?, ?, 'bossa', ?, 'SYNTHA', 'PLSYNTH00001', 'buy', 10, 100, "
    "1000, 5, 1005, 'PLN')"
)


def _primary_key(connection) -> list:
    return connection.execute(
        "SELECT constraint_column_names FROM duckdb_constraints() "
        "WHERE table_name = 'transactions' AND constraint_type = 'PRIMARY KEY'"
    ).fetchall()


def _legacy_database(path: Path) -> None:
    connection = duckdb.connect(str(path))
    connection.execute(_LEGACY_TRANSACTIONS)
    connection.execute(_INSERT, ["abc", FIRST_PORTFOLIO, datetime(2026, 1, 2, 10, 0)])
    connection.close()


def test_new_database_keys_transactions_by_portfolio(tmp_path: Path) -> None:
    connection = db.connect(tmp_path / "new.duckdb")

    assert _primary_key(connection) == [(["portfolio_id", "dedup_hash"],)]


def test_legacy_database_is_rebuilt_with_the_portfolio_in_the_key(tmp_path: Path) -> None:
    path = tmp_path / "legacy.duckdb"
    _legacy_database(path)

    connection = db.connect(path)

    assert _primary_key(connection) == [(["portfolio_id", "dedup_hash"],)]
    assert connection.execute(
        "SELECT dedup_hash, portfolio_id, instrument_name, value, net_value FROM transactions"
    ).fetchall() == [("abc", FIRST_PORTFOLIO, "SYNTHA", Decimal("1000"), Decimal("1005"))]
    assert connection.execute(
        "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'transactions_before_247'"
    ).fetchone() == (0,)


def test_rebuilt_table_takes_the_same_row_for_another_portfolio_only(tmp_path: Path) -> None:
    path = tmp_path / "legacy.duckdb"
    _legacy_database(path)
    connection = db.connect(path)
    executed_at = datetime(2026, 1, 2, 10, 0)

    connection.execute(_INSERT, ["abc", SECOND_PORTFOLIO, executed_at])

    with pytest.raises(duckdb.ConstraintException):
        connection.execute(_INSERT, ["abc", FIRST_PORTFOLIO, executed_at])


def test_rebuild_runs_once(tmp_path: Path) -> None:
    path = tmp_path / "legacy.duckdb"
    _legacy_database(path)
    db.connect(path).close()

    connection = db.connect(path)

    assert _primary_key(connection) == [(["portfolio_id", "dedup_hash"],)]
    assert connection.execute("SELECT count(*) FROM transactions").fetchone() == (1,)


_POSITION_INSERT = (
    "INSERT INTO positions (id, snapshot_id, broker, account_type, instrument_name, "
    "asset_class, quantity, avg_cost, cost_currency, market_value, market_currency, "
    "valuation_date, resolution_status) VALUES (?, ?, ?, 'regular', 'Moneta', 'other', "
    "?, ?, 'PLN', ?, 'PLN', ?, 'unresolved')"
)


def _valuations(connection) -> list:
    return connection.execute(
        "SELECT position_id, valued_on, unit_value FROM manual_valuations ORDER BY position_id"
    ).fetchall()


def test_hand_set_manual_value_becomes_one_valuation_on_its_entry_day(tmp_path: Path) -> None:
    # #288: before, the owner edited a manual position's market_value itself.
    path = tmp_path / "legacy.duckdb"
    overridden, at_cost, imported = (uuid.UUID(int=n) for n in (1, 2, 3))
    connection = db.connect(path)
    for position_id, broker, market_value in (
        (overridden, "manual", 80),
        (at_cost, "manual", 55),
        (imported, "xtb", 80),
    ):
        connection.execute(
            _POSITION_INSERT,
            [position_id, uuid.uuid4(), broker, 10, Decimal("5.5"), market_value, "2026-05-04"],
        )
    connection.close()

    db.connect(path).close()  # moves the value
    connection = db.connect(path)  # and doesn't move it twice

    assert _valuations(connection) == [(overridden, date(2026, 5, 4), Decimal("8"))]
