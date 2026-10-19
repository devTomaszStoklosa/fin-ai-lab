from datetime import datetime
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


def build_synthetic_xtb_workbook(
    extra_note: str | None = None,
    *,
    account_currency: str | None = "PLN",
    lot_open_times: tuple[object, object] | None = None,
    cash_operations: list[
        tuple[str, str, datetime, float, str] | tuple[str, str, datetime, float, str, str, str]
    ]
    | None = None,
    closed_positions: list[tuple] | None = None,
) -> bytes:
    """A small workbook shaped like the real XTB export: metadata rows before
    the header, then summary rows (Category set) interleaved with per-lot
    detail rows (Type set, Category blank) for the same instrument.

    extra_note, when given, is appended as a trailing cell on the first
    summary row — past the declared headers, so it never becomes a mapped
    field, only something a whole-file scan (e.g. injection flagging) sees.

    account_currency, when given, fills the "Open position value" metadata
    row real XTB exports carry (row 5, matching xtb_open_positions.v1.yaml's
    currency_marker) -- pass None to omit it and exercise the fallback path.

    lot_open_times, when given, fills "Open time (UTC)" on the two per-lot
    detail rows (ISAC.UK's, then ATR.PL's) -- left empty otherwise, like
    before portfolio-webapp-S10 started reading it.

    cash_operations, when given, fills the "Cash Operations" sheet the way the
    real export lays it out (metadata rows, the header, one row per
    (type, instrument, time, amount, id[, ticker, comment]), then a "Total"
    row) -- empty otherwise.

    closed_positions, when given, fills the "Closed Positions" sheet the same
    way: one row per lot (instrument, ticker, type, volume, open price, open
    time, close time, purchase value, sale value) -- purchase and sale value
    may be None, like a CFD's -- then a "Total" row without a type.
    """
    workbook = openpyxl.Workbook()
    closed_sheet = workbook.active
    closed_sheet.title = "Closed Positions"
    if closed_positions is not None:
        for label in ("Account number", "Closed Positions", "Date from (UTC)", "Date to (UTC)"):
            closed_sheet.append([label])
        closed_sheet.append(
            [
                "Instrument",
                "Ticker",
                "Category",
                "Type",
                "Volume",
                "Open Price",
                "Open Time (UTC)",
                "Close Price",
                "Close Time (UTC)",
                "Product",
                "Profit/Loss",
                "Gross Profit",
                "Purchase Value",
                "Sale Value",
            ]
        )
        for lot in closed_positions:
            name, ticker, lot_type, volume, price, opened, closed, purchase, sale = lot
            closed_sheet.append(
                [
                    *(name, ticker, "STOCK", lot_type, volume, price, opened, None, closed),
                    *("My Trades", None, None, purchase, sale),
                ]
            )
        closed_sheet.append(["Total", None, None, None, None, None, None, None, None])
    cash_sheet = workbook.create_sheet("Cash Operations")
    if cash_operations is not None:
        for label in ("Account number", "Cash Operations", "Date from (UTC)", "Date to (UTC)"):
            cash_sheet.append([label])
        cash_sheet.append(
            ["Type", "Instrument", "Ticker", "Category", "Time", "Amount", "ID", "Comment"]
        )
        for op_type, instrument, time, amount, op_id, *details in cash_operations:
            ticker, comment = (*details, "", "")[:2]
            cash_sheet.append([op_type, instrument, ticker, "", time, amount, op_id, comment])
        cash_sheet.append(["Total", "", "", "", None, sum(op[3] for op in cash_operations), "", ""])
    sheet = workbook.create_sheet("Open Positions")

    for _ in range(4):
        sheet.append([])
    sheet.append(
        ["My Trades", "Open position value", 7088.87, account_currency]
        if account_currency is not None
        else []
    )
    for _ in range(3):
        sheet.append([])

    sheet.append(XTB_OPEN_POSITIONS_HEADERS)
    padding = [None] * (len(XTB_OPEN_POSITIONS_HEADERS) - 9)
    # Net Profit % (index 12 of the tail) mirrors the real ISAC.UK export:
    # 59.4. XTB computes it correctly in account currency, unlike "Open
    # price" (69.48), which is in the instrument's own trading currency
    # (see issue #188) -- this lets tests exercise the derived-avg_cost path.
    first_row_tail = list(padding)
    first_row_tail[3] = 59.4
    first_row = [
        "My Trades",
        "MSCI ACWI",
        "ISAC.UK",
        "ETF",
        None,
        6.0,
        2745.41,
        None,
        69.48,
    ] + first_row_tail
    if extra_note is not None:
        first_row.append(extra_note)
    sheet.append(first_row)
    isac_lot_tail, atr_lot_tail = list(padding), list(padding)
    if lot_open_times is not None:
        isac_lot_tail[0], atr_lot_tail[0] = lot_open_times
    sheet.append(
        ["My Trades", "1140380016", "ISAC.UK", None, "BUY", 6.0, 2745.41, 122.24, 69.48]
        + isac_lot_tail
    )
    sheet.append(["My Trades", "Atrem", "ATR.PL", "STC", None, 1.0, 53.3, None, 12.25] + padding)
    sheet.append(
        ["My Trades", "987654321", "ATR.PL", None, "BUY", 1.0, 53.3, 53.3, 12.25] + atr_lot_tail
    )

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# Valid ISIN checksums for a made-up "SYNTH" issuer — not a real company,
# picked only to satisfy canonical.Position's checksum validation.
SYNTH_A_ISIN = "PLSYNTH00016"
SYNTH_B_ISIN = "PLSYNTH00024"


def build_synthetic_bossa_csv() -> bytes:
    """Shaped like the real Bossa "historia operacji" export (hisPW.csv):
    semicolon-delimited, cp1250, one row per transaction, "-" column carries
    K (buy) / S (sell). SYNTHA is bought then partly sold (stays open,
    weighted-average cost updates); SYNTHB is bought then fully sold (closes
    to zero, must not appear in the resulting positions)."""
    rows = [
        "data;papier;isin;ilość;-;cena;wartość;prowizja;po prowizji;waluta",
        f"01.01.2026 10:00:00;SYNTHA;{SYNTH_A_ISIN};10;K;100,00;1000,00;5,00;1005,00;PLN",
        f"05.01.2026 10:00:00;SYNTHA;{SYNTH_A_ISIN};4;S;110,00;440,00;2,00;438,00;PLN",
        f"01.01.2026 11:00:00;SYNTHB;{SYNTH_B_ISIN};5;K;50,00;250,00;1,00;251,00;PLN",
        f"02.01.2026 11:00:00;SYNTHB;{SYNTH_B_ISIN};5;S;60,00;300,00;1,00;299,00;PLN",
    ]
    return ("\r\n".join(rows) + "\r\n").encode("cp1250")


def bossa_settlement_row(
    day: str,
    kind: str,
    name: str,
    isin: str,
    quantity: str,
    price: str,
    currency: str,
    amount: str,
    ref: str = "1",
) -> str:
    """One settlement line of the Bossa financial history; kind is "kupna" or
    "sprzedaży", amount the net figure after commission (comma decimals)."""
    return (
        f"{day};Rozliczenie transakcji {kind}:;{name} ({isin}) {quantity} x {price} "
        f"{currency} nr {ref};{amount};{currency}"
    )


def build_synthetic_bossa_financial_csv(
    extra_rows: list[str] | None = None, *, with_cash_rows: bool = True
) -> bytes:
    """Shaped like the real Bossa "historia finansowa" export: cp1250,
    semicolons, `data;tytuł operacji;szczegóły;kwota;waluta`, newest first.
    The four settlement rows are the same trades as build_synthetic_bossa_csv
    (amount = the net figure after commission, details = name, ISIN, quantity
    x price, currency); with_cash_rows adds a dividend, a deposit, a fee and a
    currency exchange, which the result treats differently."""
    a, b = SYNTH_A_ISIN, SYNTH_B_ISIN
    rows = [
        "data;tytuł operacji;szczegóły;kwota;waluta",
        bossa_settlement_row("2026-01-05", "sprzedaży", "SYNTHA", a, "4", "110.0", "PLN", "438,00"),
        bossa_settlement_row("2026-01-02", "sprzedaży", "SYNTHB", b, "5", "60.00", "PLN", "299,00"),
        bossa_settlement_row("2026-01-01", "kupna", "SYNTHB", b, "5", "50.00", "PLN", "-251,00"),
        bossa_settlement_row("2026-01-01", "kupna", "SYNTHA", a, "10", "100.00", "PLN", "-1005,00"),
    ]
    if with_cash_rows:
        rows += [
            "2026-01-03;Wypłata dywidendy SYNTHA;;12,50;PLN",
            "2026-01-01;Przelew do DM BOŚ;;2000,00;PLN",
            "2026-01-01;Opłata za transakcję (XNAS);;-0,10;PLN",
            "2026-01-01;Wymiana waluty PLN/USD 3.6403;;-100,00;PLN",
        ]
    rows += extra_rows or []
    return ("\r\n".join(rows) + "\r\n").encode("cp1250")
