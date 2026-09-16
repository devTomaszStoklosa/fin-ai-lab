from datetime import date
from io import BytesIO

import openpyxl

from fin_ai_lab.portfolio_xray.importer import import_xlsx
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry
from portfolio_xray._fixtures import build_synthetic_xtb_workbook


def test_import_xlsx_maps_summary_rows_to_positions() -> None:
    registry = ParserRegistry()

    result = import_xlsx(
        build_synthetic_xtb_workbook(),
        valuation_date=date(2026, 9, 15),
        account_type="regular",
        market_currency="PLN",
        registry=registry,
    )

    assert result.errors == []
    assert result.warnings == []
    assert {p.symbol for p in result.positions} == {"ISAC.UK", "ATR.PL"}

    acwi = next(p for p in result.positions if p.symbol == "ISAC.UK")
    assert acwi.quantity == 6
    assert acwi.asset_class == "etf"
    assert acwi.resolution_status == "unresolved"

    atrem = next(p for p in result.positions if p.symbol == "ATR.PL")
    assert atrem.asset_class == "equity"


def _build_unrecognized_workbook() -> bytes:
    workbook = openpyxl.Workbook()
    workbook.active.append(["Some", "Unrelated", "Columns"])
    workbook.active.append(["a", "b", "c"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_import_xlsx_reports_unknown_format() -> None:
    registry = ParserRegistry()

    result = import_xlsx(
        _build_unrecognized_workbook(),
        valuation_date=date(2026, 9, 15),
        account_type="regular",
        market_currency="PLN",
        registry=registry,
    )

    assert result.positions == []
    assert result.errors == ["Unknown file format"]
