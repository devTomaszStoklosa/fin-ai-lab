from datetime import date, datetime
from decimal import Decimal

import pytest

pytest.importorskip("openpyxl")

from portfolio_xray._fixtures import build_synthetic_xtb_workbook  # noqa: E402

from fin_ai_lab.portfolio_webapp.cash_operations import CashOperationsError  # noqa: E402
from fin_ai_lab.portfolio_webapp.closed_lots import (  # noqa: E402
    ClosedLot,
    extract_xtb_closed_lots,
)
from fin_ai_lab.portfolio_webapp.lot_history import (  # noqa: E402
    OpenHolding,
    build_lot_history,
    xtb_key,
)
from fin_ai_lab.portfolio_webapp.xtb_symbols import (  # noqa: E402
    candidate_quote_currencies,
    quote_currency_from_lot,
    yahoo_symbol,
)

D = Decimal
OPENED = datetime(2026, 1, 1, 10, 0, 0)
CLOSED = datetime(2026, 1, 4, 16, 30, 0)


def _lot(ticker="OLD.PL", volume=10.0, opened=OPENED, closed=CLOSED, purchase=400.0, sale=450.0):
    return ("Old co", ticker, "BUY", volume, 40.0, opened, closed, purchase, sale)


def _workbook(lots, **kwargs) -> bytes:
    return build_synthetic_xtb_workbook(closed_positions=lots, **kwargs)


def test_closed_lots_are_read_with_their_holding_period_and_values() -> None:
    history = extract_xtb_closed_lots(_workbook([_lot()]))

    assert history is not None
    (lot,) = history.lots
    assert (lot.ticker, lot.instrument, lot.volume) == ("OLD.PL", "Old co", D("10.0"))
    assert (lot.opened_at, lot.closed_at) == (OPENED, CLOSED)
    assert (lot.purchase_value, lot.sale_value, lot.currency) == (D("400.0"), D("450.0"), "PLN")


def test_total_row_shorts_and_unpriced_lots_are_counted_not_used() -> None:
    lots = [
        _lot(),
        ("Short", "SHORT.US", "SELL", 1.0, 5.0, OPENED, CLOSED, 5.0, 4.0),
        ("Crypto CFD", "SOLANA", "BUY", 2.0, 100.0, OPENED, CLOSED, None, None),
        ("Bad time", "BAD.US", "BUY", 1.0, 5.0, "not a date", CLOSED, 5.0, 6.0),
    ]

    history = extract_xtb_closed_lots(_workbook(lots))

    assert history is not None
    assert [lot.ticker for lot in history.lots] == ["OLD.PL"]  # the "Total" row is no lot
    assert (history.skipped_short, history.skipped_unpriced, history.unreadable_rows) == (1, 1, 1)


def test_identical_rows_get_distinct_stable_ids() -> None:
    first = extract_xtb_closed_lots(_workbook([_lot(), _lot()]))
    again = extract_xtb_closed_lots(_workbook([_lot(), _lot()]))

    assert first is not None and again is not None
    ids = [lot.lot_id for lot in first.lots]
    assert len(set(ids)) == 2
    assert [lot.lot_id for lot in again.lots] == ids


def test_empty_sheet_means_no_history_and_unknown_currency_is_an_error() -> None:
    assert extract_xtb_closed_lots(build_synthetic_xtb_workbook()) is None
    with pytest.raises(CashOperationsError, match="account currency"):
        extract_xtb_closed_lots(_workbook([_lot()], account_currency=None))


def test_yahoo_symbols_follow_the_suffixes_seen_in_real_exports() -> None:
    assert yahoo_symbol("AAPL.US") == "AAPL"
    assert yahoo_symbol("BRK.B.US") == "BRK-B"
    assert yahoo_symbol("CDR.PL") == "CDR.WA"
    assert yahoo_symbol("EMQQ.UK") == "EMQQ.L"
    assert yahoo_symbol("URNU.DE") == "URNU.DE"
    assert yahoo_symbol("AIR.FR") == "AIR.PA"
    assert yahoo_symbol("ICHN.NL") == "ICHN.AS"
    assert yahoo_symbol("MELE.BE") == "MELE.BR"
    assert yahoo_symbol("SOLANA") is None  # no suffix: a crypto CFD
    assert yahoo_symbol("FOO.XX") is None  # a suffix nobody has seen


def test_xtb_tickers_named_differently_on_yahoo_are_renamed() -> None:
    assert yahoo_symbol("GOOGC.US") == "GOOG"
    assert yahoo_symbol("BRKB.US") == "BRK-B"
    assert yahoo_symbol("DOC1.US") == "DOC"
    assert yahoo_symbol("GPOR1.US") == "GPOR"
    assert yahoo_symbol("FI.US") == "FISV"
    assert yahoo_symbol("NEHC.US") == "NUAI"
    assert yahoo_symbol("GOOGL.US") == "GOOGL"  # only the listed tickers


def test_quote_currencies_of_brussels_and_amsterdam_listings() -> None:
    assert candidate_quote_currencies("MELE.BE") == ("EUR",)
    # Amsterdam lists in USD (ICHN.NL) or EUR: told from the lot, like London.
    assert candidate_quote_currencies("ICHN.NL") == ("USD", "EUR")
    rates = {"USD": 1.0, "EUR": 1.08}  # to a USD account
    assert quote_currency_from_lot("ICHN.NL", "USD", 1.0, rates) == "USD"
    assert quote_currency_from_lot("IWDA.NL", "USD", 1.08, rates) == "EUR"


def test_the_quote_currency_of_a_london_listing_is_read_from_the_lot() -> None:
    rates = {"USD": 1.0, "GBP": 1.33, "EUR": 1.08}  # to a USD account
    # cost per unit in the account currency / open price = XTB's own rate
    assert quote_currency_from_lot("EMQQ.UK", "USD", 1.0, rates) == "USD"
    assert quote_currency_from_lot("PRTC.UK", "USD", 1.327, rates) == "GBP"
    assert quote_currency_from_lot("EIMI.UK", "EUR", 0.859, {"USD": 0.859, "GBP": 1.16}) == "USD"
    assert quote_currency_from_lot("ODD.UK", "USD", 3.0, rates) is None  # nothing fits
    assert (
        quote_currency_from_lot("AAPL.US", "PLN", 4.0, {}) == "USD"
    )  # one candidate: no lot needed


def test_lots_become_quantity_changes_and_a_sold_instrument_gets_an_anchor() -> None:
    closed = ClosedLot(
        lot_id="a:0",
        ticker="OLD.PL",
        instrument="Old co",
        volume=D(10),
        open_price=D(40),
        opened_at=OPENED,
        closed_at=CLOSED,
        purchase_value=D(400),
        sale_value=D(450),
        currency="PLN",
    )
    held = OpenHolding(
        key="xtb:HELD.PL",
        quantity=D(3),
        dated_lots=[(D(1), date(2026, 1, 2)), (D(2), date(2026, 1, 3))],
        held_on=date(2026, 1, 5),
    )

    history = build_lot_history([closed], [held], anchored_keys={"xtb:HELD.PL"})

    assert sorted((c.key, c.on, c.quantity_change) for c in history.changes) == [
        ("xtb:HELD.PL", date(2026, 1, 2), D(1)),
        ("xtb:HELD.PL", date(2026, 1, 3), D(2)),
        (xtb_key("OLD.PL"), date(2026, 1, 1), D(10)),
        (xtb_key("OLD.PL"), date(2026, 1, 4), D(-10)),
    ]
    anchor = history.anchors[xtb_key("OLD.PL")]
    assert (anchor.unit_value, anchor.currency, anchor.as_of) == (D(45), "PLN", date(2026, 1, 4))
    assert anchor.quote_currency == "PLN"
    assert history.tickers[xtb_key("OLD.PL")] == "OLD.WA"
    assert "xtb:HELD.PL" not in history.anchors  # the snapshot prices it


def test_a_position_without_dated_lots_counts_from_the_import_day() -> None:
    held = OpenHolding("xtb:HELD.PL", D(3), dated_lots=[], held_on=date(2026, 1, 5))

    history = build_lot_history([], [held], anchored_keys={"xtb:HELD.PL"})

    assert [(c.on, c.quantity_change) for c in history.changes] == [(date(2026, 1, 5), D(3))]


def test_an_instrument_that_cannot_be_priced_is_left_out_and_named() -> None:
    crypto = ClosedLot(
        "b:0", "SOLANA", "Solana", D(2), D(100), OPENED, CLOSED, D(200), D(210), "EUR"
    )

    history = build_lot_history([crypto], [], anchored_keys=set())

    assert history.changes == []
    assert history.skipped == ["Solana"]
