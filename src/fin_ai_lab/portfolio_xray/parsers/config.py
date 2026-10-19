from typing import Literal

from pydantic import BaseModel


class RowFilter(BaseModel):
    # A data row counts as a position only when it satisfies both conditions.
    # Needed for files where summary rows and per-transaction rows are
    # interleaved in the same table (e.g. XTB Open Positions).
    require_non_empty: list[str] = []
    require_empty: list[str] = []


class CurrencyMarker(BaseModel):
    # Some brokers (XTB) state the account's own currency in a fixed
    # metadata row elsewhere in the same sheet, e.g.
    # ("My Trades", "Open position value", 7088.87, "PLN") -- rather than a
    # fixed row/column coordinate (fragile if a row gets inserted above it),
    # this scans the sheet for a cell equal to `label` and reads the
    # currency `currency_column_offset` columns to its right.
    label: str
    currency_column_offset: int


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
    # Not part of ParserConfigProposal -- the LLM never invents this, only a
    # human wires it up for a broker whose export is known to state its own
    # account currency somewhere (see CurrencyMarker). Absent for every
    # other config, which keeps relying on the caller-supplied fallback
    # currency exactly as before (issue #195).
    currency_marker: CurrencyMarker | None = None


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
