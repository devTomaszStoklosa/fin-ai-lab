from fin_ai_lab.portfolio_xray.parsers.reader import (
    apply_row_filter,
    find_matching_config,
    read_xlsx_sheets,
    rows_as_dicts,
)
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry
from portfolio_xray._fixtures import build_synthetic_xtb_workbook


def test_read_xlsx_sheets_returns_all_sheet_names() -> None:
    sheets = read_xlsx_sheets(build_synthetic_xtb_workbook())

    assert set(sheets) == {"Closed Positions", "Cash Operations", "Open Positions"}
    assert len(sheets["Open Positions"]) == 13  # 8 metadata + header + 4 data rows


def test_find_matching_config_locates_header_row_and_sheet() -> None:
    sheets = read_xlsx_sheets(build_synthetic_xtb_workbook())
    registry = ParserRegistry()

    match = find_matching_config(sheets, registry)

    assert match is not None
    config, sheet_name, header_row = match
    assert sheet_name == "Open Positions"
    assert header_row == 9
    assert config.broker == "xtb"


def test_row_filter_keeps_only_summary_rows() -> None:
    sheets = read_xlsx_sheets(build_synthetic_xtb_workbook())
    registry = ParserRegistry()
    config, sheet_name, header_row = find_matching_config(sheets, registry)

    rows = rows_as_dicts(sheets[sheet_name], header_row)
    filtered = apply_row_filter(rows, config.row_filter)

    assert [row["Instrument/Position"] for _, row in filtered] == ["MSCI ACWI", "Atrem"]
