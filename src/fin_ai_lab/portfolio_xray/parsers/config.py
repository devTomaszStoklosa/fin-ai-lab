from typing import Literal

from pydantic import BaseModel


class RowFilter(BaseModel):
    # A data row counts as a position only when it satisfies both conditions.
    # Needed for files where summary rows and per-transaction rows are
    # interleaved in the same table (e.g. XTB Open Positions).
    require_non_empty: list[str] = []
    require_empty: list[str] = []


class ParserConfig(BaseModel):
    broker: str
    version: int
    sheet_name: str | None = None
    header_row: int = 1
    row_filter: RowFilter | None = None
    expected_headers: list[str]                # full header row, used for signature matching
    column_mapping: dict[str, str]             # subset actually mapped: file header -> field
    number_format: Literal["pl", "en"] = "en"
    date_format: str = "%Y-%m-%d"
    encoding: str = "utf-8"
    delimiter: str | None = None


class ParserConfigProposal(BaseModel):
    """What the model proposes for an unrecognized format: everything in
    ParserConfig except broker/version, which the caller assigns — the model
    should not invent the broker name or pick a version number."""

    sheet_name: str | None = None
    header_row: int = 1
    row_filter: RowFilter | None = None
    expected_headers: list[str]
    column_mapping: dict[str, str]
    number_format: Literal["pl", "en"] = "en"
    date_format: str = "%Y-%m-%d"
    encoding: str = "utf-8"
    delimiter: str | None = None
