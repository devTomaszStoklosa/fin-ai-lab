from io import BytesIO

import openpyxl

from fin_ai_lab.portfolio_xray.parsers.config import ParserConfig, RowFilter
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry
from fin_ai_lab.portfolio_xray.parsers.signature import compute_signature

_MAX_HEADER_SCAN_ROWS = 20


def read_xlsx_sheets(file_bytes: bytes) -> dict[str, list[tuple[object, ...]]]:
    # read_only=True trusts the file's declared <dimension>; some exports (e.g.
    # XTB's) misdeclare it as a single cell, which would silently truncate every
    # sheet to one row. The full parser recomputes the real extent from the cells.
    workbook = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True, read_only=False)
    return {
        sheet.title: [row for row in sheet.iter_rows(values_only=True)]
        for sheet in workbook.worksheets
    }


def find_matching_config(
    sheets: dict[str, list[tuple[object, ...]]], registry: ParserRegistry
) -> tuple[ParserConfig, str, int] | None:
    for sheet_name, rows in sheets.items():
        for row_index, row in enumerate(rows[:_MAX_HEADER_SCAN_ROWS], start=1):
            headers = [str(cell) for cell in row if cell not in (None, "")]
            if not headers:
                continue
            signature = compute_signature(
                headers, delimiter=None, encoding="utf-8", sheet_name=sheet_name
            )
            config = registry.find_approved(signature)
            if config is not None:
                return config, sheet_name, row_index
    return None


def rows_as_dicts(
    rows: list[tuple[object, ...]], header_row: int
) -> list[tuple[int, dict[str, object]]]:
    header = [str(cell) if cell is not None else "" for cell in rows[header_row - 1]]
    records = []
    for offset, row in enumerate(rows[header_row:]):
        record = {name: value for name, value in zip(header, row) if name}
        if any(value is not None for value in record.values()):
            row_number = header_row + 1 + offset
            records.append((row_number, record))
    return records


def apply_row_filter(
    rows: list[tuple[int, dict[str, object]]], row_filter: RowFilter | None
) -> list[tuple[int, dict[str, object]]]:
    if row_filter is None:
        return rows
    selected = []
    for row_number, row in rows:
        if any(not row.get(column) for column in row_filter.require_non_empty):
            continue
        if any(row.get(column) for column in row_filter.require_empty):
            continue
        selected.append((row_number, row))
    return selected
