from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

import openpyxl
from portfolio_xray._fixtures import build_synthetic_xtb_workbook

from fin_ai_lab.portfolio_webapp.lots import (
    OpenLot,
    extract_xtb_open_lots,
    lots_matching_quantity,
    parse_open_time,
)
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry


def test_extracts_one_lot_per_buy_detail_row() -> None:
    workbook = build_synthetic_xtb_workbook(
        lot_open_times=(datetime(2025, 3, 14, 9, 30), "02.06.2025 15:04:05")
    )

    lots = extract_xtb_open_lots(workbook, ParserRegistry())

    assert lots == [
        OpenLot(
            symbol="ISAC.UK",
            lot_ref="1140380016",
            quantity=Decimal("6.0"),
            opened_on=date(2025, 3, 14),
        ),
        OpenLot(
            symbol="ATR.PL",
            lot_ref="987654321",
            quantity=Decimal("1.0"),
            opened_on=date(2025, 6, 2),
        ),
    ]


def test_lot_without_readable_open_time_is_skipped() -> None:
    workbook = build_synthetic_xtb_workbook(lot_open_times=("not a date", None))

    assert extract_xtb_open_lots(workbook, ParserRegistry()) == []


def test_non_xtb_file_yields_no_lots() -> None:
    workbook = openpyxl.Workbook()
    workbook.active.append(["Totally", "Unrelated", "Headers"])
    buffer = BytesIO()
    workbook.save(buffer)

    assert extract_xtb_open_lots(buffer.getvalue(), ParserRegistry()) == []


def test_parse_open_time_accepts_known_shapes() -> None:
    assert parse_open_time(datetime(2025, 1, 2, 3, 4)) == date(2025, 1, 2)
    assert parse_open_time(date(2025, 1, 2)) == date(2025, 1, 2)
    assert parse_open_time("2025-01-02 03:04:05") == date(2025, 1, 2)
    assert parse_open_time("02.01.2025") == date(2025, 1, 2)
    assert parse_open_time(45659.5) == date(2025, 1, 2)  # Excel serial date
    assert parse_open_time("") is None
    assert parse_open_time(None) is None
    assert parse_open_time(True) is None


def test_lots_kept_only_when_they_add_up_to_the_position() -> None:
    lots = [
        OpenLot(symbol="A", lot_ref="1", quantity=Decimal(2), opened_on=date(2025, 1, 1)),
        OpenLot(symbol="A", lot_ref="2", quantity=Decimal(3), opened_on=date(2025, 2, 1)),
        OpenLot(symbol="B", lot_ref="3", quantity=Decimal(1), opened_on=date(2025, 1, 1)),
        OpenLot(symbol="C", lot_ref="4", quantity=Decimal(1), opened_on=date(2025, 1, 1)),
    ]

    matched = lots_matching_quantity(lots, {"A": Decimal(5), "B": Decimal(4)})

    # B's lots cover only part of its quantity (one lot unreadable), C isn't
    # a position at all -- neither may date any history.
    assert list(matched) == ["A"]
    assert [lot.lot_ref for lot in matched["A"]] == ["1", "2"]
