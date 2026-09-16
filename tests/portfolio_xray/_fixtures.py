from io import BytesIO

import openpyxl

XTB_OPEN_POSITIONS_HEADERS = [
    "Product",
    "Instrument/Position",
    "Ticker",
    "Category",
    "Type",
    "Volume",
    "Value",
    "Current price",
    "Open price",
    "Open time (UTC)",
    "Stop Loss",
    "Take Profit",
    "Net Profit %",
    "Net Profit",
    "Gross Profit",
    "Margin",
    "Open Commission",
    "Swap",
    "Rollover",
]


def build_synthetic_xtb_workbook() -> bytes:
    """A small workbook shaped like the real XTB export: metadata rows before
    the header, then summary rows (Category set) interleaved with per-lot
    detail rows (Type set, Category blank) for the same instrument."""
    workbook = openpyxl.Workbook()
    workbook.active.title = "Closed Positions"
    workbook.create_sheet("Cash Operations")
    sheet = workbook.create_sheet("Open Positions")

    for _ in range(8):
        sheet.append([])

    sheet.append(XTB_OPEN_POSITIONS_HEADERS)
    padding = [None] * (len(XTB_OPEN_POSITIONS_HEADERS) - 9)
    sheet.append(
        ["My Trades", "MSCI ACWI", "ISAC.UK", "ETF", None, 6.0, 2745.41, None, 69.48] + padding
    )
    sheet.append(
        ["My Trades", "1140380016", "ISAC.UK", None, "BUY", 6.0, 2745.41, 122.24, 69.48] + padding
    )
    sheet.append(
        ["My Trades", "Atrem", "ATR.PL", "STC", None, 1.0, 53.3, None, 12.25] + padding
    )
    sheet.append(
        ["My Trades", "987654321", "ATR.PL", None, "BUY", 1.0, 53.3, 53.3, 12.25] + padding
    )

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
