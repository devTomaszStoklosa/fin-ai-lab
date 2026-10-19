from datetime import UTC, datetime
from pathlib import Path

import duckdb

# Real portfolio data (rule 7): stays under data/private/, never tracked by git.
DEFAULT_DB_PATH = Path("data/private/portfolio_webapp.duckdb")

# Full schema up front rather than migrating per slice (02-spec.md already
# fixes every table's shape). Most tables are unused until their own slice
# lands (S2 positions/snapshots, S8 transactions, S9 aggregators) -- only
# `portfolios` is read/written in S1.
SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolios (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    broker TEXT,
    account_type TEXT,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id UUID PRIMARY KEY,
    portfolio_id UUID NOT NULL,
    broker TEXT NOT NULL,
    valuation_date DATE NOT NULL,
    imported_at TIMESTAMP NOT NULL,
    source_file_date_min DATE,
    source_file_date_max DATE
);

CREATE TABLE IF NOT EXISTS positions (
    id UUID PRIMARY KEY,
    snapshot_id UUID NOT NULL,
    broker TEXT NOT NULL,
    account_type TEXT NOT NULL,
    instrument_name TEXT NOT NULL,
    isin TEXT,
    symbol TEXT,
    asset_class TEXT NOT NULL,
    quantity DECIMAL(24, 8) NOT NULL,
    avg_cost DECIMAL(24, 8),
    cost_currency TEXT,
    market_value DECIMAL(24, 8),
    market_currency TEXT,
    valuation_date DATE NOT NULL,
    resolution_status TEXT NOT NULL,
    figi TEXT,
    ticker TEXT,
    exchange_code TEXT,
    identification_rule TEXT,
    quote_currency TEXT
);

-- Bossa (S8) only; dedup_hash is the full-row hash from ledger.py::dedup_key.
-- It identifies a row within one portfolio only (#247): the same hisPW file
-- imported into two portfolios is two sets of rows.
CREATE TABLE IF NOT EXISTS transactions (
    dedup_hash TEXT NOT NULL,
    portfolio_id UUID NOT NULL,
    broker TEXT NOT NULL,
    executed_at TIMESTAMP NOT NULL,
    instrument_name TEXT NOT NULL,
    isin TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity DECIMAL(24, 8) NOT NULL,
    price DECIMAL(24, 8) NOT NULL,
    value DECIMAL(24, 8) NOT NULL,
    commission DECIMAL(24, 8) NOT NULL,
    net_value DECIMAL(24, 8) NOT NULL,
    currency TEXT NOT NULL,
    PRIMARY KEY (portfolio_id, dedup_hash)
);

-- #241: XTB "Cash Operations" rows. op_id is XTB's own ID, so re-importing an
-- overlapping export adds only what is new. kind groups XTB's type for the
-- investment result (cash_operations.py); amount is signed, in `currency`.
-- #265: ticker and comment link a dividend to its instrument (XTB only).
CREATE TABLE IF NOT EXISTS cash_operations (
    portfolio_id UUID NOT NULL,
    op_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    op_type TEXT NOT NULL,
    instrument TEXT,
    occurred_at TIMESTAMP NOT NULL,
    amount DECIMAL(24, 8) NOT NULL,
    currency TEXT NOT NULL,
    ticker TEXT,
    comment TEXT,
    PRIMARY KEY (portfolio_id, op_id)
);

-- #249: XTB "Closed Positions" lots. lot_id is a hash of the row plus its
-- occurrence number (the export has no ID). With the open lots they say what
-- was held on every day; volume/open/close bound each lot's holding period.
CREATE TABLE IF NOT EXISTS closed_lots (
    portfolio_id UUID NOT NULL,
    lot_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    instrument TEXT NOT NULL,
    volume DECIMAL(24, 8) NOT NULL,
    open_price DECIMAL(24, 8) NOT NULL,
    opened_at TIMESTAMP NOT NULL,
    closed_at TIMESTAMP NOT NULL,
    purchase_value DECIMAL(24, 8) NOT NULL,
    sale_value DECIMAL(24, 8) NOT NULL,
    currency TEXT NOT NULL,
    PRIMARY KEY (portfolio_id, lot_id)
);

CREATE TABLE IF NOT EXISTS reports (
    id UUID PRIMARY KEY,
    snapshot_id UUID NOT NULL,
    generated_at TIMESTAMP NOT NULL,
    model TEXT NOT NULL,
    cost_usd DECIMAL(12, 6) NOT NULL,
    content_md TEXT NOT NULL
);

-- S9. member_instrument_keys: ISIN, or "broker:symbol" when the instrument
-- has none (02-spec.md REQ-065) -- never a position row's id, which changes
-- on every re-import.
CREATE TABLE IF NOT EXISTS aggregators (
    id UUID PRIMARY KEY,
    portfolio_id UUID NOT NULL,
    name TEXT NOT NULL,
    member_instrument_keys TEXT[],
    member_aggregator_ids UUID[]
);

-- S10. One row per purchase ("lot") behind an imported position, when the
-- broker's export states it (XTB's Open Positions detail rows) -- only used
-- to date holdings before the import itself (portfolio_webapp/lots.py).
-- lot_ref is the broker's own position number, kept for traceability.
CREATE TABLE IF NOT EXISTS position_lots (
    position_id UUID NOT NULL,
    lot_ref TEXT NOT NULL,
    quantity DECIMAL(24, 8) NOT NULL,
    opened_on DATE NOT NULL
);

-- S11 breakdowns ("podziały"): the owner's own trees of groups for the
-- shares chart. breakdown_assignments' primary key is REQ-081 itself: one
-- group per instrument within a breakdown, so shares add up to 100%.
CREATE TABLE IF NOT EXISTS breakdowns (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    is_default BOOLEAN NOT NULL,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS breakdown_groups (
    id UUID PRIMARY KEY,
    breakdown_id UUID NOT NULL,
    parent_id UUID,
    name TEXT NOT NULL,
    position INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS breakdown_assignments (
    breakdown_id UUID NOT NULL,
    instrument_key TEXT NOT NULL,
    group_id UUID NOT NULL,
    PRIMARY KEY (breakdown_id, instrument_key)
);

-- S12: the owner's answer on whether two per-broker instrument keys are one
-- asset (instruments.py). key_a < key_b, so a pair has exactly one row and a
-- later answer replaces the earlier one.
CREATE TABLE IF NOT EXISTS instrument_decisions (
    key_a TEXT NOT NULL,
    key_b TEXT NOT NULL,
    same BOOLEAN NOT NULL,
    decided_at TIMESTAMP NOT NULL,
    PRIMARY KEY (key_a, key_b)
);

-- #277: the listing that prices each ISIN the Bossa ledger traded, held or
-- sold (traded_instruments.py). One row per ISIN for every portfolio: the
-- same instrument in two accounts is looked up once. status `unresolved`
-- keeps an ISIN without a listing from being asked about again.
CREATE TABLE IF NOT EXISTS instrument_listings (
    isin TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    figi TEXT,
    ticker TEXT,
    exchange_code TEXT,
    identification_rule TEXT,
    quote_currency TEXT,
    identified_at TIMESTAMP NOT NULL
);

-- #285: the owner's own Yahoo symbol and quote currency for an instrument the
-- import could not price (instrument_overrides.py). Keyed like
-- instrument_decisions, for every portfolio; either column may be empty.
CREATE TABLE IF NOT EXISTS instrument_overrides (
    instrument_key TEXT PRIMARY KEY,
    yahoo_ticker TEXT,
    quote_currency TEXT,
    updated_at TIMESTAMP NOT NULL
);

-- #288: the owner's own valuations of a manual position (an asset no exchange
-- quotes, e.g. a gold coin) -- manual_valuations.py. unit_value is per unit,
-- in PLN like every manual position; one valuation per day, a later one on
-- the same day replaces it.
CREATE TABLE IF NOT EXISTS manual_valuations (
    position_id UUID NOT NULL,
    valued_on DATE NOT NULL,
    unit_value DECIMAL(24, 8) NOT NULL,
    recorded_at TIMESTAMP NOT NULL,
    PRIMARY KEY (position_id, valued_on)
);

-- #226 (P5 web). status: pending/running/awaiting_confirmation/done/failed.
-- result_json holds a serialized CommitteeReport (variant single/committee)
-- or ComparisonReport (variant compare) -- shape picked by `variant`, never
-- guessed from the JSON itself.
CREATE TABLE IF NOT EXISTS committee_jobs (
    id UUID PRIMARY KEY,
    portfolio_id UUID NOT NULL,
    snapshot_id UUID NOT NULL,
    variant TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    model TEXT NOT NULL,
    cost_usd DECIMAL(12, 6),
    error TEXT,
    result_json TEXT
);
"""

# CREATE TABLE IF NOT EXISTS only applies to tables that don't exist yet, so a
# column added to an already-created table (e.g. this file on a machine that
# ran an earlier slice) needs its own idempotent statement here.
MIGRATIONS = """
ALTER TABLE positions ADD COLUMN IF NOT EXISTS identification_rule TEXT;
ALTER TABLE positions ADD COLUMN IF NOT EXISTS quote_currency TEXT;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS instrument_name TEXT;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS value DECIMAL(24, 8);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS net_value DECIMAL(24, 8);
ALTER TABLE cash_operations ADD COLUMN IF NOT EXISTS ticker TEXT;
ALTER TABLE cash_operations ADD COLUMN IF NOT EXISTS comment TEXT;
"""

# Named columns, not SELECT *: a database migrated through MIGRATIONS has
# instrument_name/value/net_value physically at the end of the table.
_TRANSACTIONS_COLUMNS = (
    "dedup_hash, portfolio_id, broker, executed_at, instrument_name, isin, side, "
    "quantity, price, value, commission, net_value, currency"
)


def _scope_transactions_key_to_portfolio(connection: duckdb.DuckDBPyConnection) -> None:
    """#247: before, dedup_hash alone was the primary key, so a second
    portfolio could not store a row the first one already had. DuckDB cannot
    drop a primary key, so the table is rebuilt from SCHEMA and its rows
    copied over -- all of it or nothing, in one transaction."""
    primary_keys = connection.execute(
        "SELECT constraint_column_names FROM duckdb_constraints() "
        "WHERE table_name = 'transactions' AND constraint_type = 'PRIMARY KEY'"
    ).fetchall()
    if primary_keys != [(["dedup_hash"],)]:
        return
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute("ALTER TABLE transactions RENAME TO transactions_before_247")
        connection.execute(SCHEMA)
        connection.execute(
            f"INSERT INTO transactions ({_TRANSACTIONS_COLUMNS}) "
            f"SELECT {_TRANSACTIONS_COLUMNS} FROM transactions_before_247"
        )
        connection.execute("DROP TABLE transactions_before_247")
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


def _move_overridden_manual_values_to_valuations(connection: duckdb.DuckDBPyConnection) -> None:
    """#288: before, the owner moved a manual position's value away from its
    cost by editing market_value itself. That value becomes one valuation on
    the position's entry day, so its history looks exactly as before. Safe
    to run on every start: afterwards market_value always follows the
    latest valuation, or the cost when there is none, so no row matches
    twice. A cent of tolerance keeps a quantity with more decimals than the
    column stores from looking like an override. 'manual' is
    repository.MANUAL_BROKER, spelled out: the schema module stays below
    the repository, never imports it."""
    connection.execute(
        "INSERT INTO manual_valuations (position_id, valued_on, unit_value, recorded_at) "
        "SELECT p.id, p.valuation_date, p.market_value / p.quantity, ? FROM positions p "
        "WHERE p.broker = 'manual' AND p.quantity > 0 AND p.market_value IS NOT NULL "
        "AND p.avg_cost IS NOT NULL AND abs(p.market_value - p.quantity * p.avg_cost) >= 0.01 "
        "AND NOT EXISTS (SELECT 1 FROM manual_valuations v WHERE v.position_id = p.id)",
        [datetime.now(UTC)],
    )


def connect(db_path: Path = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(db_path))
    connection.execute(SCHEMA)
    connection.execute(MIGRATIONS)
    _scope_transactions_key_to_portfolio(connection)
    _move_overridden_manual_values_to_valuations(connection)
    return connection
