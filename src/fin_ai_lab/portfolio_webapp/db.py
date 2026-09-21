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
    identification_rule TEXT
);

-- Bossa (S8) only; dedup_hash is the full-row hash from ledger.py::dedup_key.
CREATE TABLE IF NOT EXISTS transactions (
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
"""

# CREATE TABLE IF NOT EXISTS only applies to tables that don't exist yet, so a
# column added to an already-created table (e.g. this file on a machine that
# ran an earlier slice) needs its own idempotent statement here.
MIGRATIONS = """
ALTER TABLE positions ADD COLUMN IF NOT EXISTS identification_rule TEXT;
"""


def connect(db_path: Path = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(db_path))
    connection.execute(SCHEMA)
    connection.execute(MIGRATIONS)
    return connection
