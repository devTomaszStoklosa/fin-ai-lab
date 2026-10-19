from datetime import date
from decimal import Decimal

import pytest

from fin_ai_lab.portfolio_webapp.valuation import (
    Anchor,
    Lot,
    MissingFxRateError,
    QuantityChange,
    SnapshotHoldings,
    captured_gain,
    composition_changes,
    day_range,
    fx_move,
    prior_holdings_value_series,
    quantities_from_changes,
    quantities_from_snapshots,
    return_index,
    unit_value_series,
    value_series,
)

D = Decimal


def _days(start: str, end: str) -> list[date]:
    return day_range(date.fromisoformat(start), date.fromisoformat(end))


def test_day_range_is_inclusive_and_calendar_daily() -> None:
    assert _days("2026-01-30", "2026-02-02") == [
        date(2026, 1, 30),
        date(2026, 1, 31),
        date(2026, 2, 1),
        date(2026, 2, 2),
    ]


# --- quantities: snapshot brokers (XTB) -------------------------------------


def test_snapshot_quantity_holds_until_next_import() -> None:
    days = _days("2026-01-01", "2026-01-06")
    snapshots = [
        SnapshotHoldings(date(2026, 1, 2), {"A": D(10)}),
        SnapshotHoldings(date(2026, 1, 5), {"A": D(4), "B": D(1)}),
    ]

    quantities = quantities_from_snapshots(snapshots, days)

    # Nothing before the first import (no lots to date it), a sale only
    # shows up on the import that proves it.
    assert quantities["A"] == [D(0), D(10), D(10), D(10), D(4), D(4)]
    assert quantities["B"] == [D(0), D(0), D(0), D(0), D(1), D(1)]


def test_lots_date_holdings_before_the_first_import() -> None:
    days = _days("2026-01-01", "2026-01-05")
    snapshots = [
        SnapshotHoldings(
            date(2026, 1, 4),
            {"A": D(5)},
            lots={"A": [Lot(D(2), date(2026, 1, 2)), Lot(D(3), date(2026, 1, 3))]},
        )
    ]

    assert quantities_from_snapshots(snapshots, days)["A"] == [D(0), D(2), D(5), D(5), D(5)]


def test_lots_bought_between_imports_count_from_their_own_date() -> None:
    days = _days("2026-01-01", "2026-01-06")
    snapshots = [
        # An older import without lot detail (e.g. from before S10).
        SnapshotHoldings(date(2026, 1, 2), {"A": D(10)}),
        SnapshotHoldings(
            date(2026, 1, 5),
            {"A": D(15)},
            lots={"A": [Lot(D(10), date(2025, 12, 1)), Lot(D(5), date(2026, 1, 4))]},
        ),
    ]

    quantities = quantities_from_snapshots(snapshots, days)

    # Jan 1: only the Dec lot (before any base). Jan 2-3: base 10 -- the Dec
    # lot is already inside it, never counted twice. Jan 4: +5 bought after
    # the base import.
    assert quantities["A"] == [D(10), D(10), D(10), D(15), D(15), D(15)]


def test_sell_and_rebuy_between_imports_never_exceeds_both_imports() -> None:
    days = _days("2026-01-01", "2026-01-06")
    snapshots = [
        SnapshotHoldings(date(2026, 1, 1), {"A": D(1)}),
        # The old unit was sold and a new one bought on Jan 3 -- when the
        # old one went is not in either export.
        SnapshotHoldings(date(2026, 1, 6), {"A": D(1)}, lots={"A": [Lot(D(1), date(2026, 1, 3))]}),
    ]

    assert quantities_from_snapshots(snapshots, days)["A"] == [D(1)] * 6


# --- quantities: ledgers and manual positions -------------------------------


def test_changes_accumulate_per_day_and_never_go_negative() -> None:
    days = _days("2026-01-01", "2026-01-04")
    changes = [
        QuantityChange("A", date(2026, 1, 2), D(10)),
        QuantityChange("A", date(2026, 1, 3), D(-4)),
        # A sell with no matching buy in the imported history (a gap).
        QuantityChange("B", date(2026, 1, 2), D(-1)),
    ]

    quantities = quantities_from_changes(changes, days)

    assert quantities["A"] == [D(0), D(10), D(6), D(6)]
    assert quantities["B"] == [D(0), D(0), D(0), D(0)]


# --- unit value --------------------------------------------------------------


def test_unit_value_follows_price_ratio_from_anchor() -> None:
    days = _days("2026-01-01", "2026-01-04")
    anchor = Anchor(unit_value=D(100), currency="PLN", as_of=date(2026, 1, 3))
    # Jan 3 is a Saturday-like gap: no close, the Jan 2 close carries over.
    closes = {date(2026, 1, 1): D(40), date(2026, 1, 2): D(50), date(2026, 1, 4): D(55)}

    units = unit_value_series(anchor, days, closes, {})

    assert units.base == [D(80), D(100), D(100), D(110)]
    assert units.native == units.base
    assert units.last_price_date == date(2026, 1, 4)


def test_foreign_quote_moves_with_its_fx_rate_too() -> None:
    days = _days("2026-01-01", "2026-01-02")
    # A USD stock held in a PLN account: the broker records PLN, Yahoo quotes USD.
    anchor = Anchor(unit_value=D(400), currency="PLN", as_of=date(2026, 1, 1), quote_currency="USD")
    closes = {date(2026, 1, 1): D(100), date(2026, 1, 2): D(110)}
    fx = {"USD": {date(2026, 1, 1): D(4), date(2026, 1, 2): D("3.8")}}

    units = unit_value_series(anchor, days, closes, fx)

    # +10% in USD, -5% USD/PLN: 400 * 1.1 * 0.95.
    assert units.base == [D(400), D("418.0")]
    assert units.missing_quote_fx is None


def test_pence_quote_uses_pound_fx_ratio() -> None:
    days = _days("2026-01-01", "2026-01-02")
    anchor = Anchor(unit_value=D(50), currency="PLN", as_of=date(2026, 1, 1), quote_currency="GBp")
    closes = {date(2026, 1, 1): D(1000), date(2026, 1, 2): D(1000)}
    fx = {"GBP": {date(2026, 1, 1): D(5), date(2026, 1, 2): D("5.5")}}

    assert unit_value_series(anchor, days, closes, fx).base == [D(50), D("55.0")]


def test_missing_quote_fx_keeps_price_ratio_and_reports_it() -> None:
    days = _days("2026-01-01", "2026-01-02")
    anchor = Anchor(unit_value=D(10), currency="PLN", as_of=date(2026, 1, 1), quote_currency="USD")
    closes = {date(2026, 1, 1): D(1), date(2026, 1, 2): D(2)}

    units = unit_value_series(anchor, days, closes, {})

    assert units.base == [D(10), D(20)]
    assert units.missing_quote_fx == "USD"


def test_foreign_account_currency_converts_to_pln_per_day() -> None:
    days = _days("2026-01-01", "2026-01-02")
    anchor = Anchor(unit_value=D(10), currency="EUR", as_of=date(2026, 1, 1))
    fx = {"EUR": {date(2026, 1, 1): D("4.2"), date(2026, 1, 2): D("4.3")}}

    units = unit_value_series(anchor, days, None, fx)

    assert units.native == [D(10), D(10)]
    assert units.base == [D("42.0"), D("43.0")]


def test_foreign_account_currency_without_fx_is_an_error_not_a_guess() -> None:
    anchor = Anchor(unit_value=D(10), currency="EUR", as_of=date(2026, 1, 1))

    with pytest.raises(MissingFxRateError):
        unit_value_series(anchor, _days("2026-01-01", "2026-01-02"), None, {})


def test_manual_position_ignores_market_data() -> None:
    days = _days("2026-01-01", "2026-01-02")
    anchor = Anchor(
        unit_value=D(7), currency="PLN", as_of=date(2026, 1, 1), moves_with_market=False
    )
    closes = {date(2026, 1, 1): D(1), date(2026, 1, 2): D(3)}

    units = unit_value_series(anchor, days, closes, {})

    assert units.base == [D(7), D(7)]
    assert units.last_price_date is None


# --- fx move (one day, #283) ---------------------------------------------------


def test_fx_move_of_foreign_quote_in_pln_account_is_its_rate_change() -> None:
    # #283's example: a USD stock in a PLN account, USD/PLN 4.00 -> 4.20.
    fx = {"USD": {date(2026, 1, 5): D("4.00"), date(2026, 1, 12): D("4.20")}}

    move = fx_move("PLN", "USD", date(2026, 1, 5), date(2026, 1, 12), fx)

    assert move == D("1.05")


def test_fx_move_in_foreign_account_divides_out_the_account_currency() -> None:
    # A USD stock in a EUR account: USD/PLN +5%, EUR/PLN +2%.
    fx = {
        "USD": {date(2026, 1, 5): D("4.00"), date(2026, 1, 12): D("4.20")},
        "EUR": {date(2026, 1, 5): D("4.25"), date(2026, 1, 12): D("4.335")},
    }

    move = fx_move("EUR", "USD", date(2026, 1, 5), date(2026, 1, 12), fx)

    assert move == D("1.05") / D("1.02")


def test_fx_move_is_one_for_same_or_unknown_quote_currency() -> None:
    since, until = date(2026, 1, 5), date(2026, 1, 12)

    assert fx_move("PLN", "PLN", since, until, {}) == D(1)
    assert fx_move("PLN", None, since, until, {}) == D(1)
    # Pence move with pounds: no factor for a GBp listing in a GBP account.
    assert fx_move("GBP", "GBp", since, until, {}) == D(1)


def test_fx_move_uses_last_rate_on_or_before_each_day() -> None:
    # Imported on a Saturday, valued on a Sunday: Friday's rates both times.
    fx = {"USD": {date(2026, 1, 2): D("4.00"), date(2026, 1, 9): D("3.80")}}

    move = fx_move("PLN", "USD", date(2026, 1, 3), date(2026, 1, 11), fx)

    assert move == D("0.95")


def test_fx_move_without_quote_rates_is_an_error_for_the_caller() -> None:
    with pytest.raises(MissingFxRateError):
        fx_move("PLN", "USD", date(2026, 1, 5), date(2026, 1, 12), {})


def test_owner_revaluations_step_the_unit_from_their_own_day() -> None:
    # #288: a gold coin bought for 100, valued at 120 on Jan 3 and 90 on Jan 5.
    days = _days("2026-01-01", "2026-01-06")
    anchor = Anchor(
        unit_value=D(100),
        currency="PLN",
        as_of=date(2026, 1, 2),
        moves_with_market=False,
        revaluations=((date(2026, 1, 3), D(120)), (date(2026, 1, 5), D(90))),
    )
    closes = {date(2026, 1, 1): D(1), date(2026, 1, 6): D(3)}

    units = unit_value_series(anchor, days, closes, {})

    assert units.base == [D(100), D(100), D(120), D(120), D(90), D(90)]
    assert units.native == units.base
    assert units.last_price_date is None  # still no daily quotes


def test_owner_revaluation_on_the_purchase_day_replaces_the_purchase_price() -> None:
    days = _days("2026-01-01", "2026-01-02")
    anchor = Anchor(
        unit_value=D(100),
        currency="PLN",
        as_of=date(2026, 1, 1),
        moves_with_market=False,
        revaluations=((date(2026, 1, 1), D(8)),),
    )

    assert unit_value_series(anchor, days, None, {}).base == [D(8), D(8)]


# --- totals and changes -------------------------------------------------------


def test_value_series_sums_only_instruments_with_a_unit_value() -> None:
    quantities = {"A": [D(1), D(2)], "B": [D(5), D(5)]}
    units = {"A": [D(10), D(11)]}

    assert value_series(quantities, units, 2) == [D(10), D(22)]


# --- return without deposits, purchases and sales (#273) ---------------------


def test_prior_holdings_value_prices_yesterdays_quantity_at_todays_unit() -> None:
    quantities = {"A": [D(1), D(3), D(3)], "B": [D(2), D(2), D(0)]}
    units = {"A": [D(10), D(11), D(12)], "B": [D(5), D(6), D(7)]}

    # Day 1: 1 A and 2 B held overnight -> 1*11 + 2*6; the 2 A bought on
    # day 1 do not count until day 2. Day 2: 3*12 + 2*7 (B sold that day).
    assert prior_holdings_value_series(quantities, units, 3) == [D(0), D(23), D(50)]


def test_prior_holdings_value_leaves_out_instruments_without_a_unit_value() -> None:
    quantities = {"A": [D(1), D(1)], "B": [D(5), D(5)]}

    assert prior_holdings_value_series(quantities, {"A": [D(10), D(12)]}, 2) == [D(0), D(12)]


def test_return_index_ignores_a_purchase() -> None:
    # 100 grows 10% on day 1; on day 2 the price is flat but 1000 more is
    # bought -- the value jumps, the return does not.
    values = [D(100), D(110), D(1110)]
    prior = [D(0), D(110), D(110)]

    assert return_index(values, prior, [D(0)] * 3) == [D(1), D("1.1"), D("1.1")]


def test_return_index_ignores_a_sale() -> None:
    # Everything sold on day 1 at an unchanged price: no gain, no loss.
    values = [D(100), D(0), D(0)]
    prior = [D(0), D(100), D(0)]

    assert return_index(values, prior, [D(0)] * 3) == [D(1), D(1), D(1)]


def test_return_index_counts_a_dividend_on_the_day_it_is_credited() -> None:
    values = [D(200), D(200), D(220)]
    prior = [D(0), D(200), D(220)]
    dividends = [D(0), D(4), D(0)]

    assert return_index(values, prior, dividends) == [D(1), D("1.02"), D("1.122")]


def test_return_index_stays_flat_after_an_empty_day() -> None:
    # Nothing held on day 0; the first purchase on day 1 starts the index.
    values = [D(0), D(50), D(55)]
    prior = [D(0), D(0), D(55)]

    assert return_index(values, prior, [D(0)] * 3) == [D(1), D(1), D("1.1")]


def test_captured_gain_is_price_moves_plus_dividends_not_purchases() -> None:
    # +10 from prices on day 1, a 1000 purchase on day 2 (not a gain), a
    # 4 dividend on day 2.
    values = [D(100), D(110), D(1110)]
    prior = [D(0), D(110), D(110)]
    dividends = [D(0), D(0), D(4)]

    assert captured_gain(values, prior, dividends) == D(14)


def test_composition_changes_skip_the_starting_state() -> None:
    days = _days("2026-01-01", "2026-01-03")
    quantities = {"A": [D(5), D(5), D(8)], "B": [D(2), D(0), D(0)]}

    assert composition_changes(quantities, days) == [
        (date(2026, 1, 2), "B", D(-2)),
        (date(2026, 1, 3), "A", D(3)),
    ]
