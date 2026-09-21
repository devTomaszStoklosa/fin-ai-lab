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


class ColumnMapping(BaseModel):
    file_header: str
    field: str


class ParserConfigProposal(BaseModel):
    """What the model proposes for an unrecognized format: everything in
    ParserConfig except broker/version, which the caller assigns — the model
    should not invent the broker name or pick a version number."""

    sheet_name: str | None = None
    header_row: int = 1
    row_filter: RowFilter | None = None
    expected_headers: list[str]
    # A list of pairs, not dict[str, str] like ParserConfig.column_mapping:
    # a dict field's JSON schema needs `additionalProperties`, which
    # Gemini's Developer API (the free/non-Vertex endpoint this repo uses)
    # rejects in structured output ("additionalProperties is only
    # supported in Gemini Enterprise Agent Platform mode"). A fixed-shape
    # list has no such field. propose_and_validate_config converts this
    # back into a dict before building the real ParserConfig.
    column_mapping: list[ColumnMapping]
    number_format: Literal["pl", "en"] = "en"
    date_format: str = "%Y-%m-%d"
    encoding: str = "utf-8"
    delimiter: str | None = None
