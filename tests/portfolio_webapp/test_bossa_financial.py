from datetime import datetime
from decimal import Decimal

from portfolio_xray._fixtures import (
    SYNTH_A_ISIN,
    bossa_settlement_row,
    build_synthetic_bossa_csv,
    build_synthetic_bossa_financial_csv,
)

from fin_ai_lab.portfolio_webapp.bossa_financial import (
    DividendTitle,
    is_financial_history,
    parse_dividend_title,
    parse_financial_history,
)

D = Decimal


def _trades(csv_bytes: bytes):
    return parse_financial_history(csv_bytes).transactions


def test_settlement_rows_become_trades_with_commission_from_the_net_amount() -> None:
    trades = {
        (t.side, t.isin, t.quantity): t for t in _trades(build_synthetic_bossa_financial_csv())
    }

    buy = trades[("buy", SYNTH_A_ISIN, D(10))]
    assert (buy.price, buy.value, buy.net_value, buy.commission) == (
        D("100.00"),
        D("1000.00"),
        D("1005.00"),
        D("5.00"),
    )
    sell = trades[("sell", SYNTH_A_ISIN, D(4))]
    assert (sell.value, sell.net_value, sell.commission) == (D("440.00"), D("438.00"), D("2.00"))
    assert buy.currency == sell.currency == "PLN"
    assert buy.instrument_name == "SYNTHA"


def test_a_price_with_a_thousands_space_is_read() -> None:
    row = bossa_settlement_row(
        "2026-09-18",
        "kupna",
        "Mercadolibre, Inc.",
        "US58733R1023",
        "1",
        "1 790.00",
        "USD",
        "-1794,30",
    )

    (trade,) = _trades(build_synthetic_bossa_financial_csv([row], with_cash_rows=False))[-1:]

    assert (trade.quantity, trade.price, trade.commission, trade.currency) == (
        D(1),
        D("1790.00"),
        D("4.30"),
        "USD",
    )


def test_buys_are_ordered_before_sells_within_a_day() -> None:
    rows = [
        bossa_settlement_row(
            "2026-02-02", "sprzedaży", "SYNTHA", SYNTH_A_ISIN, "1", "10.00", "PLN", "10,00"
        ),
        bossa_settlement_row(
            "2026-02-02", "kupna", "SYNTHA", SYNTH_A_ISIN, "1", "10.00", "PLN", "-10,00"
        ),
    ]

    trades = _trades(build_synthetic_bossa_financial_csv(rows, with_cash_rows=False))[-2:]
    by_side = {t.side: t.executed_at for t in trades}

    assert by_side["buy"] < by_side["sell"]
    assert by_side["buy"].date() == by_side["sell"].date() == datetime(2026, 2, 2).date()


def test_dividends_deposits_and_fees_become_cash_operations() -> None:
    history = parse_financial_history(build_synthetic_bossa_financial_csv())

    assert [(op.kind, op.amount, op.currency) for op in history.operations] == [
        ("dividend", D("12.50"), "PLN"),
        ("transfer", D("2000.00"), "PLN"),
        ("other", D("-0.10"), "PLN"),
    ]  # the currency exchange is neither
    assert history.unknown_titles == []
    assert history.unreadable_rows == 0


def test_unknown_titles_and_unreadable_rows_are_reported_not_guessed() -> None:
    rows = [
        "2026-01-04;Coś zupełnie nowego;;5,00;PLN",
        "2026-01-04;Rozliczenie transakcji kupna:;not the usual shape;-5,00;PLN",
        "kaput;Wypłata dywidendy X;;1,00;PLN",
    ]

    history = parse_financial_history(
        build_synthetic_bossa_financial_csv(rows, with_cash_rows=False)
    )

    assert history.unknown_titles == ["Coś zupełnie nowego"]
    assert history.unreadable_rows == 2
    assert len(history.transactions) == 4  # only the four settlement rows that parse


def test_identical_rows_are_told_apart_by_their_number_in_the_file() -> None:
    fee = "2026-01-04;Opłata za transakcję (XNYS);;-0,07;USD"

    history = parse_financial_history(
        build_synthetic_bossa_financial_csv([fee, fee], with_cash_rows=False)
    )

    ids = [op.op_id for op in history.operations]
    assert len(ids) == len(set(ids)) == 2
    again = parse_financial_history(
        build_synthetic_bossa_financial_csv([fee, fee], with_cash_rows=False)
    )
    assert [op.op_id for op in again.operations] == ids  # stable across exports


def test_only_the_financial_history_header_is_recognised() -> None:
    assert is_financial_history(build_synthetic_bossa_financial_csv())
    assert not is_financial_history(build_synthetic_bossa_csv())
    assert not is_financial_history(b"")


def test_dividend_title_names_the_company_by_short_name_or_ticker() -> None:
    assert parse_dividend_title("Wypłata dywidendy PEKAO") == DividendTitle("PEKAO", False)
    assert parse_dividend_title("Wypłata dywidendy netto HCA 85% USD") == DividendTitle(
        "HCA", False, D("0.15")
    )
    assert parse_dividend_title("Wypłata dywidendy brutto HIDD USD") == DividendTitle(
        "HIDD", False, D(0)
    )
    assert parse_dividend_title("Korekta dywidendy ARR") == DividendTitle("ARR", True)


def test_a_title_naming_no_company_gives_none() -> None:
    assert parse_dividend_title("Wypłata dywidendy") is None
    assert parse_dividend_title("Przelew do DM BOŚ") is None


def test_a_plain_title_states_no_withholding_rate() -> None:
    # A GPW share in IKE ("Wypłata dywidendy PEKAO") or "netto" without a
    # percentage: the title doesn't say, the tax rules decide (#267).
    assert parse_dividend_title("Wypłata dywidendy PEKAO").withheld is None
    assert parse_dividend_title("Wypłata dywidendy netto ABC USD").withheld is None
    assert parse_dividend_title("Wypłata dywidendy netto BWMX 90% USD").withheld == D("0.10")
