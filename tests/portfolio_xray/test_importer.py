from datetime import date
from decimal import Decimal
from io import BytesIO

import openpyxl

from fin_ai_lab.portfolio_xray.importer import build_position, import_xlsx
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
    # "Open price" (69.48) is in the instrument's own trading currency, not
    # PLN -- the real cost was 1722.34 PLN (cross-checked against XTB's Cash
    # Operations sheet, see issue #188). avg_cost is derived from Value and
    # XTB's own "Net Profit %" (59.4) instead of trusting Open price as-is.
    assert acwi.cost_currency == "PLN"
    assert acwi.avg_cost is not None
    cost_basis = acwi.quantity * acwi.avg_cost
    assert abs(cost_basis - Decimal("1722.34")) < Decimal("0.01")

    atrem = next(p for p in result.positions if p.symbol == "ATR.PL")
    assert atrem.asset_class == "equity"
    # Atrem's fixture row has no "Net Profit %" -- falls back to today's
    # behavior (Open price trusted as-is, since for a PLN-listed stock it
    # genuinely already is PLN).
    assert atrem.avg_cost == Decimal("12.25")


def test_import_xlsx_detects_account_currency_from_marker_row() -> None:
    # A genuinely USD-denominated XTB account (issue #195) -- the "Open
    # position value" row states USD, which must override the "PLN" passed
    # in as market_currency, for every position in the file.
    registry = ParserRegistry()

    result = import_xlsx(
        build_synthetic_xtb_workbook(account_currency="USD"),
        valuation_date=date(2026, 9, 15),
        account_type="regular",
        market_currency="PLN",
        registry=registry,
    )

    assert result.errors == []
    assert result.warnings == []
    assert {p.market_currency for p in result.positions} == {"USD"}
    assert {p.cost_currency for p in result.positions} == {"USD"}


def test_import_xlsx_falls_back_to_default_currency_when_marker_row_missing() -> None:
    # A file that doesn't match the real export's shape (e.g. a future XTB
    # format change) -- must not silently mislabel positions, falls back to
    # the caller-supplied default and says so via a warning.
    registry = ParserRegistry()

    result = import_xlsx(
        build_synthetic_xtb_workbook(account_currency=None),
        valuation_date=date(2026, 9, 15),
        account_type="regular",
        market_currency="PLN",
        registry=registry,
    )

    assert result.errors == []
    assert result.warnings == [
        "Could not detect account currency from 'Open position value' row -- "
        "defaulting to PLN"
    ]
    assert {p.market_currency for p in result.positions} == {"PLN"}


def test_build_position_falls_back_to_open_price_without_broker_return() -> None:
    # No "net_profit_pct" mapped at all -- e.g. a broker/parser that
    # doesn't report one. Must behave exactly like before this fix.
    row = {"Name": "Test Co", "Price": "10.5", "Qty": "2", "Value": "999"}
    position = build_position(
        row,
        {
            "Name": "instrument_name",
            "Price": "avg_cost",
            "Qty": "quantity",
            "Value": "market_value",
        },
        broker="test",
        account_type="regular",
        market_currency="PLN",
        valuation_date=date(2026, 9, 15),
    )
    assert position.avg_cost == Decimal("10.5")


def test_build_position_falls_back_when_broker_return_is_total_loss() -> None:
    # net_profit_pct = -100 would divide by zero (1 + -100/100 == 0) --
    # cost can't be recovered from a wiped-out position this way, so this
    # must fall back to the raw "Open price" column instead of crashing.
    row = {
        "Name": "Test Co",
        "Price": "10.5",
        "Qty": "2",
        "Value": "0",
        "Net Profit %": "-100",
    }
    position = build_position(
        row,
        {
            "Name": "instrument_name",
            "Price": "avg_cost",
            "Qty": "quantity",
            "Value": "market_value",
            "Net Profit %": "net_profit_pct",
        },
        broker="test",
        account_type="regular",
        market_currency="PLN",
        valuation_date=date(2026, 9, 15),
    )
    assert position.avg_cost == Decimal("10.5")


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
