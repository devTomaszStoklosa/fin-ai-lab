"""Finds and stores the listing of every ISIN a Bossa ledger traded that has
none yet (fin-ai-lab#277): OpenFIGI for the listings, Yahoo for the quote
currency, traded_instruments.py for the choice between listings. Network
access goes through the injected client and fetcher, so tests run on canned
answers."""

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import replace
from typing import Protocol

import duckdb

from fin_ai_lab.portfolio_webapp import repository
from fin_ai_lab.portfolio_webapp.traded_instruments import (
    FALLBACK_CURRENCY,
    InstrumentListing,
    choose_listing,
    latest_trade_currencies,
)
from fin_ai_lab.portfolio_xray.identification.openfigi import Listing
from fin_ai_lab.portfolio_xray.ledger import BossaTransaction

# Same reasoning as valuation_builder.PRICE_FETCH_CONCURRENCY: yfinance is
# unofficial and sometimes blocks bursts.
QUOTE_CURRENCY_CONCURRENCY = 4

QuoteCurrencyFetcher = Callable[[str], str | None]


class ListingsClient(Protocol):
    def listings_by_isin(
        self, jobs: list[tuple[str, str | None]]
    ) -> Awaitable[list[list[Listing]]]: ...


async def identify_missing_listings(
    connection: duckdb.DuckDBPyConnection,
    transactions: Iterable[BossaTransaction],
    client: ListingsClient,
    quote_currency_fetcher: QuoteCurrencyFetcher,
) -> list[str]:
    """Stores a listing for each traded ISIN not identified yet; returns the
    import warnings. A failed OpenFIGI lookup stores nothing, so the next
    import asks again -- it never fails the import itself."""
    known = repository.list_instrument_listings(connection)
    currencies = {
        isin: currency
        for isin, currency in latest_trade_currencies(transactions).items()
        if isin not in known
    }
    if not currencies:
        return []
    try:
        listings = await identify_listings(currencies, client, quote_currency_fetcher)
    except Exception:
        # OpenFIGI unreachable or answering errors after its retries: the
        # trades are already stored, only their daily quotes wait.
        return [
            f"Nie udało się ustalić notowań {len(currencies)} instrumentów (OpenFIGI "
            "niedostępne) — ich wartość na wykresie jest stała; zaimportuj plik ponownie później."
        ]
    repository.save_instrument_listings(connection, listings)
    return []


async def identify_listings(
    currencies: dict[str, str],
    client: ListingsClient,
    quote_currency_fetcher: QuoteCurrencyFetcher,
) -> list[InstrumentListing]:
    """One InstrumentListing per ISIN in `currencies` (ISIN -> trade
    currency). An ISIN with no listing chosen in its own currency is asked
    about once more in FALLBACK_CURRENCY."""
    isins = list(currencies)
    answers = await client.listings_by_isin([(isin, currencies[isin]) for isin in isins])
    chosen: dict[str, tuple[Listing, str]] = {}
    for isin, listings in zip(isins, answers, strict=True):
        choice = choose_listing(listings, currencies[isin])
        if choice is not None:
            chosen[isin] = choice

    retry = [isin for isin in isins if isin not in chosen and currencies[isin] != FALLBACK_CURRENCY]
    if retry:
        answers = await client.listings_by_isin([(isin, FALLBACK_CURRENCY) for isin in retry])
        for isin, listings in zip(retry, answers, strict=True):
            choice = choose_listing(listings, FALLBACK_CURRENCY)
            if choice is not None:
                listing, rule = choice
                chosen[isin] = (listing, f"{rule} (no listing for the {currencies[isin]} trade)")

    semaphore = asyncio.Semaphore(QUOTE_CURRENCY_CONCURRENCY)

    async def one(isin: str) -> InstrumentListing:
        if isin not in chosen:
            return InstrumentListing(isin=isin, status="unresolved")
        listing, rule = chosen[isin]
        result = InstrumentListing(
            isin=isin,
            status="resolved",
            figi=listing.figi,
            ticker=listing.ticker,
            exchange_code=listing.exchange_code,
            identification_rule=rule,
        )
        async with semaphore:
            quote_currency = await _quote_currency(result, quote_currency_fetcher)
        return replace(result, quote_currency=quote_currency)

    return list(await asyncio.gather(*(one(isin) for isin in isins)))


async def _quote_currency(listing: InstrumentListing, fetcher: QuoteCurrencyFetcher) -> str | None:
    if listing.yahoo_ticker is None:
        return None
    try:
        return await asyncio.to_thread(fetcher, listing.yahoo_ticker)
    except Exception:
        # yfinance is unofficial and sometimes blocked (docs/DATA-SOURCES.md):
        # without its currency the listing still moves the value by price.
        return None
