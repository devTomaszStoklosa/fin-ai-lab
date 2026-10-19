from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from fin_ai_lab.portfolio_webapp.cash_operations import CashOperation
from fin_ai_lab.portfolio_webapp.dividends import (
    BossaDividendLinker,
    PaymentSource,
    XtbDividendLinker,
    convert_payments,
    dividend_payments,
    summarize,
)

D = Decimal
PORTFOLIO = uuid4()
TODAY = date(2026, 10, 13)


def _op(
    op_type: str,
    amount: str,
    at: datetime,
    *,
    kind: str = "dividend",
    currency: str = "USD",
    instrument: str | None = None,
    ticker: str | None = None,
    comment: str | None = None,
) -> CashOperation:
    return CashOperation(
        op_id=str(uuid4()),
        kind=kind,
        op_type=op_type,
        instrument=instrument,
        occurred_at=at,
        amount=D(amount),
        currency=currency,
        ticker=ticker,
        comment=comment,
    )


def _xtb(op_type: str, amount: str, at: datetime, comment: str = "MSFT.US USD 0.91/ SHR"):
    return _op(op_type, amount, at, instrument="Microsoft", ticker="MSFT.US", comment=comment)


def _same_key(key: str) -> str:
    return key


def test_xtb_dividend_and_its_withholding_tax_are_one_payment() -> None:
    at = datetime(2026, 9, 10, 7, 19, 44)
    operations = [
        _xtb("Dividend", "3.64", at),
        _xtb("Withholding tax", "-0.55", at, comment="MSFT.US USD WHT 15%"),
        _op("Deposit", "100", at, kind="transfer"),
    ]

    (payment,) = dividend_payments(PORTFOLIO, operations, XtbDividendLinker())

    assert payment.amount == D("3.09")
    assert payment.paid_on == date(2026, 9, 10)
    assert payment.source == PaymentSource("xtb:MSFT.US", "Microsoft", False)


def test_xtb_correction_is_a_payment_of_its_own() -> None:
    day = datetime(2025, 11, 28, 14, 5)
    operations = [
        _xtb("Dividend", "0.57", day, comment="ATR.PL PLN 0.5700/ SHR"),
        _xtb("Dividend", "-2.06", day.replace(hour=15), comment="corr ATR.PL USD 0.5700/ SHR"),
    ]

    payments = dividend_payments(PORTFOLIO, operations, XtbDividendLinker())

    assert sorted((p.amount, p.source.is_correction) for p in payments) == [
        (D("-2.06"), True),
        (D("0.57"), False),
    ]


def test_xtb_row_without_ticker_stays_unlinked_under_its_name() -> None:
    operation = _op("Dividend", "1", datetime(2026, 1, 2), instrument="Atrem")

    assert XtbDividendLinker().link(operation) == PaymentSource(None, "Atrem", False)


def test_bossa_links_by_trade_name_or_openfigi_ticker_ignoring_case() -> None:
    linker = BossaDividendLinker(
        by_name={"PEKAO": ("PLPEKAO00016", "PEKAO")},
        by_ticker={"HCA": ("US40412C1018", "HCA Healthcare, Inc")},
    )
    day = datetime(2026, 9, 30)

    assert linker.link(_op("Wypłata dywidendy Pekao", "1", day)) == PaymentSource(
        "PLPEKAO00016", "PEKAO", False
    )
    assert linker.link(_op("Wypłata dywidendy netto HCA 85% USD", "1", day)) == PaymentSource(
        "US40412C1018", "HCA Healthcare, Inc", False, D("0.15")
    )
    assert linker.link(_op("Korekta dywidendy MURAPOL", "1", day)) == PaymentSource(
        None, "MURAPOL", True
    )


def test_each_payment_is_converted_at_the_rate_of_its_own_day() -> None:
    payments = dividend_payments(
        PORTFOLIO,
        [
            _xtb("Dividend", "10", datetime(2026, 1, 2)),
            _xtb("Dividend", "10", datetime(2026, 1, 6)),
        ],
        XtbDividendLinker(),
    )
    rates = {"USD": {date(2026, 1, 2): D("4.00"), date(2026, 1, 5): D("4.20")}}

    converted = convert_payments(payments, rates)

    # 6 January has no rate of its own: the last one before it counts.
    assert [(c.rate, c.base_amount) for c in converted] == [
        (D("4.00"), D("40.00")),
        (D("4.20"), D("42.00")),
    ]


def test_payments_without_a_rate_are_listed_but_left_out_of_the_sums() -> None:
    payments = dividend_payments(
        PORTFOLIO,
        [
            _op("Dividend", "5", datetime(2026, 3, 1), currency="PLN", instrument="Atrem"),
            _op("Dividend", "7", datetime(2026, 3, 1), currency="CHF", instrument="Nestle"),
        ],
        XtbDividendLinker(),
    )

    history = summarize(convert_payments(payments, {}), today=TODAY, asset_key=_same_key)

    assert history.total == D("5")
    assert history.missing_currencies == ["CHF"]
    assert {i.name: i.payment_count for i in history.instruments} == {"Atrem": 1, "Nestle": 1}


def test_summary_by_year_month_instrument_and_recent_periods() -> None:
    operations = [
        _op("Dividend", "1", datetime(2024, 5, 1), currency="PLN", instrument="Atrem", ticker="A"),
        _op("Dividend", "2", datetime(2025, 9, 1), currency="PLN", instrument="Atrem", ticker="A"),
        _op("Dividend", "4", datetime(2026, 2, 1), currency="PLN", instrument="Atrem", ticker="A"),
        _op("Dividend", "8", datetime(2026, 2, 9), currency="PLN", instrument="Bank", ticker="B"),
    ]
    payments = dividend_payments(PORTFOLIO, operations, XtbDividendLinker())

    history = summarize(convert_payments(payments, {}), today=TODAY, asset_key=_same_key)

    assert history.total == D("15")
    assert history.current_year == D("12")
    assert history.last_12_months == D("12")  # 1 September 2025 is more than a year ago
    assert [(y.year, y.total) for y in history.years] == [
        (2024, D("1")),
        (2025, D("2")),
        (2026, D("12")),
    ]
    assert history.years[2].months[1] == D("12")  # February
    assert [(i.name, i.total, i.last_12_months, i.payment_count) for i in history.instruments] == [
        ("Bank", D("8"), D("8"), 1),
        ("Atrem", D("7"), D("4"), 3),
    ]
    assert history.instruments[1].last_paid_on == date(2026, 2, 1)


def test_one_asset_paying_into_two_portfolios_is_one_instrument_row() -> None:
    other = uuid4()
    xtb = dividend_payments(
        PORTFOLIO,
        [
            _op(
                "Dividend",
                "3",
                datetime(2026, 6, 1),
                currency="PLN",
                instrument="Pekao",
                ticker="PEO.PL",
            )
        ],
        XtbDividendLinker(),
    )
    bossa = dividend_payments(
        other,
        [_op("Wypłata dywidendy PEKAO", "5", datetime(2026, 6, 2), currency="PLN")],
        BossaDividendLinker({"PEKAO": ("PLPEKAO00016", "PEKAO")}, {}),
    )
    joined = {"xtb:PEO.PL": "PLPEKAO00016"}

    history = summarize(
        convert_payments(xtb + bossa, {}), today=TODAY, asset_key=lambda k: joined.get(k, k)
    )

    (instrument,) = history.instruments
    assert (instrument.instrument_key, instrument.name, instrument.total) == (
        "PLPEKAO00016",
        "Pekao",  # the mixed-case name reads better than the short code
        D("8"),
    )


def test_no_payments_gives_an_empty_current_year() -> None:
    history = summarize([], today=TODAY, asset_key=_same_key)

    assert history.total == D("0")
    assert [(y.year, y.total) for y in history.years] == [(2026, D("0"))]
    assert history.instruments == []


def test_xtb_tax_row_states_its_withholding_rate() -> None:
    at = datetime(2026, 9, 10, 7, 19, 44)
    linker = XtbDividendLinker()

    assert linker.link(_xtb("Dividend", "3.64", at)).withheld is None
    tax = linker.link(_xtb("Withholding tax", "-0.55", at, comment="MSFT.US USD WHT 15%"))
    assert tax.withheld == D("0.15")
