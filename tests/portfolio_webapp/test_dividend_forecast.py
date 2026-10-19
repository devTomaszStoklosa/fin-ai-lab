from datetime import date
from decimal import Decimal

from fin_ai_lab.portfolio_webapp.dividend_forecast import (
    Holding,
    PerShareDividend,
    YahooListing,
    combine,
    estimate,
)
from fin_ai_lab.portfolio_webapp.dividend_tax import DividendTax

D = Decimal
TODAY = date(2026, 10, 13)
RATES = {"PLN": D(1), "USD": D("4.00"), "GBP": D("5.00")}


def _quarterly(amount: str = "0.91") -> list[tuple[date, Decimal]]:
    return [
        (date(2025, 8, 20), D(amount)),  # more than a year ago: not repeated
        (date(2025, 11, 20), D(amount)),
        (date(2026, 2, 19), D(amount)),
        (date(2026, 5, 21), D(amount)),
        (date(2026, 8, 20), D(amount)),
    ]


def _holding(listing: YahooListing | None, own=(), quantity: str = "10") -> Holding:
    return Holding(
        key="MSFT", name="Microsoft", quantity=D(quantity), listing=listing, own=list(own)
    )


def test_last_12_months_repeat_in_the_same_months_at_todays_rate() -> None:
    listing = YahooListing(_quarterly(), "USD", D("400"))

    result = estimate(_holding(listing), today=TODAY, rates=RATES)

    # 0.91 USD x 10 shares x 4.00 PLN, in February, May, August and November.
    paid = D("36.40")
    assert result.months == [0, paid, 0, 0, paid, 0, 0, paid, 0, 0, paid, 0]
    assert result.total == D("145.60")
    assert (result.source, result.per_share, result.currency) == ("yahoo", D("3.64"), "USD")
    assert result.yield_fraction == D("3.64") / D("400")
    assert not result.mismatch


def test_pence_are_converted_to_pounds_but_the_yield_stays_unit_free() -> None:
    listing = YahooListing([(date(2026, 6, 18), D("21.14"))], "GBp", D("1000"))

    result = estimate(_holding(listing, quantity="100"), today=TODAY, rates=RATES)

    assert (result.per_share, result.currency) == (D("0.2114"), "GBP")
    assert result.total == D("105.70")  # 0.2114 GBP x 100 x 5.00
    assert result.yield_fraction == D("21.14") / D("1000")


def test_listing_that_pays_nothing_estimates_zero_from_yahoo() -> None:
    result = estimate(_holding(YahooListing([], "USD", D("200"))), today=TODAY, rates=RATES)

    assert (result.source, result.total, result.per_share) == ("yahoo", D(0), None)


def test_unknown_to_yahoo_falls_back_to_the_brokers_own_per_share_amounts() -> None:
    own = [PerShareDividend(date(2026, 9, 22), D("0.72"), "PLN")]

    result = estimate(
        _holding(YahooListing([], None, None), own=own, quantity="5"), today=TODAY, rates=RATES
    )

    assert result.source == "history"
    assert result.months[8] == D("3.60")  # September
    assert result.yield_fraction is None


def test_no_ticker_and_no_history_is_reported_as_no_data() -> None:
    result = estimate(_holding(None), today=TODAY, rates=RATES)

    assert (result.source, result.total) == ("none", D(0))


def test_yahoo_and_the_statement_disagreeing_by_a_quarter_is_flagged() -> None:
    # Yahoo says 0.91 per payout, the account was paid 0.60 (34% less).
    own = [PerShareDividend(date(2026, 9, 10), D("0.60"), "USD")]

    flagged = estimate(
        _holding(YahooListing(_quarterly(), "USD", D("400")), own=own), today=TODAY, rates=RATES
    )
    close = estimate(
        _holding(
            YahooListing(_quarterly(), "USD", D("400")),
            own=[PerShareDividend(date(2026, 9, 10), D("0.91"), "USD")],
        ),
        today=TODAY,
        rates=RATES,
    )

    assert flagged.mismatch
    assert not close.mismatch
    assert flagged.total == close.total  # the flag never changes the amount


def test_currency_without_a_rate_leaves_the_row_out_of_the_sums() -> None:
    listing = YahooListing(_quarterly(), "CHF", D("100"))

    result = estimate(_holding(listing), today=TODAY, rates=RATES)

    assert result.missing_currency == "CHF"
    assert result.total == D(0)


def test_one_asset_in_two_portfolios_is_one_row() -> None:
    listing = YahooListing(_quarterly(), "USD", D("400"))
    first = estimate(_holding(listing, quantity="10"), today=TODAY, rates=RATES)
    second = estimate(_holding(listing, quantity="5"), today=TODAY, rates=RATES)
    other = estimate(
        Holding(key="AAPL", name="Apple", quantity=D(1), listing=None), today=TODAY, rates=RATES
    )

    rows = combine([first, other, second])

    assert [(r.key, r.quantity, r.total) for r in rows] == [
        ("MSFT", D(15), D("218.40")),
        ("AAPL", D(1), D(0)),
    ]


def test_tax_turns_gross_months_into_what_reaches_the_account() -> None:
    listing = YahooListing(_quarterly(), "USD", D("400"))
    holding = Holding(
        key="MSFT",
        name="Microsoft",
        quantity=D(10),
        listing=listing,
        tax=DividendTax(D("0.15"), D("0.04"), "statement"),
    )

    result = estimate(holding, today=TODAY, rates=RATES)

    assert result.total == D("145.60")
    assert result.credited == D("123.76")  # 15% withheld at source
    assert result.top_up == D("5.824")  # 4% still due in the tax return, not subtracted
    assert (result.withheld, result.tax_basis) == (D("0.15"), "statement")


def test_unknown_tax_leaves_the_gross_amount() -> None:
    result = estimate(
        _holding(YahooListing(_quarterly(), "USD", D("400"))), today=TODAY, rates=RATES
    )

    assert result.credited == result.total
    assert result.tax_basis == "unknown"


def test_same_company_in_ike_and_on_a_regular_account_sums_but_shows_no_single_rate() -> None:
    listing = YahooListing(_quarterly(), "USD", D("400"))
    ike = estimate(
        Holding(
            key="MSFT",
            name="Microsoft",
            quantity=D(10),
            listing=listing,
            tax=DividendTax(D("0.15"), D(0), "statement"),
        ),
        today=TODAY,
        rates=RATES,
    )
    regular = estimate(
        Holding(
            key="MSFT",
            name="Microsoft",
            quantity=D(10),
            listing=listing,
            tax=DividendTax(D("0.15"), D("0.04"), "statement"),
        ),
        today=TODAY,
        rates=RATES,
    )

    (row,) = combine([ike, regular])

    assert row.credited == D("247.52")
    assert row.top_up == D("5.824")  # only the regular account owes it
    assert (row.withheld, row.tax_basis) == (D("0.15"), "statement")  # same rate here

    other = estimate(
        Holding(
            key="MSFT",
            name="Microsoft",
            quantity=D(10),
            listing=listing,
            tax=DividendTax(D("0.27"), D(0), "rule"),
        ),
        today=TODAY,
        rates=RATES,
    )
    (mixed,) = combine([ike, other])
    assert (mixed.withheld, mixed.tax_basis) == (None, "mixed")
