from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from fin_ai_lab.portfolio_webapp import db, repository  # noqa: E402
from fin_ai_lab.portfolio_webapp.traded_instruments import (  # noqa: E402
    InstrumentListing,
    choose_listing,
    latest_trade_currencies,
)
from fin_ai_lab.portfolio_webapp.traded_instruments_builder import (  # noqa: E402
    identify_listings,
    identify_missing_listings,
)
from fin_ai_lab.portfolio_xray.identification.openfigi import Listing  # noqa: E402
from fin_ai_lab.portfolio_xray.ledger import BossaTransaction  # noqa: E402


def _listing(ticker: str, exchange: str, security_type: str = "Common Stock") -> Listing:
    return Listing(
        figi=f"BBG-{ticker}-{exchange}",
        ticker=ticker,
        exchange_code=exchange,
        security_type=security_type,
    )


def _trade(isin: str, currency: str, day: int) -> BossaTransaction:
    return BossaTransaction(
        executed_at=datetime(2026, 1, day, 10),
        instrument_name=isin,
        isin=isin,
        side="buy",
        quantity=Decimal(1),
        price=Decimal(10),
        value=Decimal(10),
        commission=Decimal(0),
        net_value=Decimal(10),
        currency=currency,
    )


# Shapes of real OpenFIGI answers, checked live 2026-10-14 (fin-ai-lab#277).


def test_usd_stock_is_priced_by_its_us_composite_listing() -> None:
    listings = [_listing("WING", code) for code in ("UA", "US", "UN", "UW", "VY")]

    chosen, rule = choose_listing(listings, "USD")

    assert (chosen.ticker, chosen.exchange_code) == ("WING", "US")
    assert rule == "US listing for a USD trade"


def test_usd_fund_is_priced_by_its_london_line_not_the_us_otc_one() -> None:
    listings = [
        _listing("VUAA", "LN", "ETP"),
        _listing("VGFPF", "US", "ETP"),
        _listing("VUAA", "SW", "ETP"),
    ]

    chosen, _ = choose_listing(listings, "USD")

    assert (chosen.ticker, chosen.exchange_code) == ("VUAA", "LN")


def test_pln_trade_is_priced_by_its_gpw_listing() -> None:
    listings = [_listing("PKN", code) for code in ("PW", "EO", "XH", "XF")]

    chosen, rule = choose_listing(listings, "PLN")

    assert (chosen.ticker, chosen.exchange_code) == ("PKN", "PW")
    assert rule == "PW listing for a PLN trade"


def test_only_listing_on_an_exchange_yahoo_does_not_know_is_not_chosen() -> None:
    # Moderna bought in PLN: OpenFIGI's only PLN line is "MRNAPLN".
    assert choose_listing([_listing("MRNAPLN", "ER")], "PLN") is None


def test_only_listing_on_a_known_exchange_is_chosen_in_any_currency() -> None:
    chosen, rule = choose_listing([_listing("ABC", "LN", "ETP")], "EUR")

    assert chosen.ticker == "ABC"
    assert rule == "only listing in currency"


def test_no_rule_for_several_listings_in_another_currency() -> None:
    assert choose_listing([_listing("ABC", "GY"), _listing("ABC", "LN")], "EUR") is None


def test_latest_trade_names_the_currency() -> None:
    trades = [_trade("X", "USD", 5), _trade("X", "PLN", 2), _trade("Y", "PLN", 1)]

    assert latest_trade_currencies(trades) == {"X": "USD", "Y": "PLN"}


def test_yahoo_ticker_of_a_listing() -> None:
    assert InstrumentListing("I", "resolved", ticker="SGLD", exchange_code="LN").yahoo_ticker == (
        "SGLD.L"
    )
    assert InstrumentListing("I", "resolved", ticker="WING", exchange_code="US").yahoo_ticker == (
        "WING"
    )
    assert InstrumentListing("I", "unresolved").yahoo_ticker is None


class _FakeListingsClient:
    """Canned listings per (ISIN, currency); records every request."""

    def __init__(self, listings: dict[tuple[str, str | None], list[Listing]]) -> None:
        self._listings = listings
        self.requests: list[list[tuple[str, str | None]]] = []

    async def listings_by_isin(self, jobs: list[tuple[str, str | None]]) -> list[list[Listing]]:
        self.requests.append(jobs)
        return [self._listings.get(job, []) for job in jobs]


class _FailingListingsClient:
    async def listings_by_isin(self, jobs: list[tuple[str, str | None]]) -> list[list[Listing]]:
        raise ConnectionError("OpenFIGI down")


async def test_a_pln_trade_without_a_quoted_listing_is_looked_up_again_in_usd() -> None:
    client = _FakeListingsClient(
        {
            ("MRNA_ISIN", "PLN"): [_listing("MRNAPLN", "ER")],
            ("MRNA_ISIN", "USD"): [_listing("MRNA", "US"), _listing("MRNA", "UW")],
            ("PKN_ISIN", "PLN"): [_listing("PKN", "PW"), _listing("PKN", "EO")],
        }
    )
    currencies = {"MRNA_ISIN": "PLN", "PKN_ISIN": "PLN", "GONE_ISIN": "USD"}
    quote_currencies = {"MRNA": "USD", "PKN.WA": "PLN"}

    listings = await identify_listings(currencies, client, quote_currencies.get)

    by_isin = {listing.isin: listing for listing in listings}
    assert client.requests[1] == [("MRNA_ISIN", "USD")]  # USD trade not asked twice
    assert by_isin["MRNA_ISIN"].yahoo_ticker == "MRNA"
    assert by_isin["MRNA_ISIN"].quote_currency == "USD"
    assert by_isin["MRNA_ISIN"].identification_rule == (
        "US listing for a USD trade (no listing for the PLN trade)"
    )
    assert by_isin["PKN_ISIN"].yahoo_ticker == "PKN.WA"
    assert by_isin["PKN_ISIN"].quote_currency == "PLN"
    assert by_isin["GONE_ISIN"] == InstrumentListing(isin="GONE_ISIN", status="unresolved")


async def test_failed_quote_currency_lookup_keeps_the_listing() -> None:
    client = _FakeListingsClient({("X", "USD"): [_listing("X", "US")]})

    def failing(ticker: str) -> str | None:
        raise RuntimeError("yfinance blocked")

    (listing,) = await identify_listings({"X": "USD"}, client, failing)

    assert listing.ticker == "X"
    assert listing.quote_currency is None


async def test_only_isins_not_identified_yet_are_looked_up(tmp_path: Path) -> None:
    connection = db.connect(tmp_path / "test.duckdb")
    repository.save_instrument_listings(
        connection, [InstrumentListing(isin="KNOWN", status="unresolved")]
    )
    client = _FakeListingsClient({("NEW", "USD"): [_listing("NEW", "US")]})

    warnings = await identify_missing_listings(
        connection, [_trade("KNOWN", "PLN", 1), _trade("NEW", "USD", 2)], client, lambda t: "USD"
    )

    assert warnings == []
    assert client.requests == [[("NEW", "USD")]]
    stored = repository.list_instrument_listings(connection)
    assert stored["NEW"].yahoo_ticker == "NEW"
    assert stored["NEW"].quote_currency == "USD"
    assert stored["KNOWN"].status == "unresolved"


async def test_failed_openfigi_lookup_stores_nothing_and_warns(tmp_path: Path) -> None:
    connection = db.connect(tmp_path / "test.duckdb")

    warnings = await identify_missing_listings(
        connection, [_trade("NEW", "USD", 2)], _FailingListingsClient(), lambda t: None
    )

    assert len(warnings) == 1
    assert "OpenFIGI" in warnings[0]
    assert repository.list_instrument_listings(connection) == {}
