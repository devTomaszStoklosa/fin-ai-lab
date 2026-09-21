import uuid
from datetime import UTC, datetime

import duckdb

PortfolioRow = tuple[uuid.UUID, str, str | None, str | None, datetime]


def list_portfolios(connection: duckdb.DuckDBPyConnection) -> list[PortfolioRow]:
    return connection.execute(
        "SELECT id, name, broker, account_type, created_at FROM portfolios ORDER BY created_at"
    ).fetchall()


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
