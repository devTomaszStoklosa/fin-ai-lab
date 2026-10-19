"""Checks the owner's entry for an instrument against Yahoo before it is
stored (fin-ai-lab#285): a symbol Yahoo has no closes for would only leave
the value flat without saying why. Network access goes through the injected
fetchers, so tests run on canned answers."""

import asyncio
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

from fin_ai_lab.portfolio_webapp.instrument_overrides import InstrumentOverride

# Enough trading days that a listing Yahoo knows has at least one close.
CHECK_WINDOW_DAYS = 31

ClosesFetcher = Callable[[str, date, bool], dict[date, Decimal] | None]
QuoteCurrencyFetcher = Callable[[str], str | None]


class UnknownYahooSymbolError(Exception):
    def __init__(self, ticker: str) -> None:
        super().__init__(f"Yahoo has no closes for {ticker}")
        self.ticker = ticker


class YahooUnavailableError(Exception):
    pass


async def checked_override(
    key: str,
    yahoo_ticker: str | None,
    quote_currency: str | None,
    *,
    today: date,
    closes_fetcher: ClosesFetcher,
    quote_currency_fetcher: QuoteCurrencyFetcher,
) -> InstrumentOverride:
    """The entry to store: the symbol only once Yahoo has closes for it, and
    the symbol's currency from Yahoo where the owner left it empty (still
    empty when Yahoo doesn't say -- the owner can pick it later)."""
    if yahoo_ticker is None:
        return InstrumentOverride(key=key, quote_currency=quote_currency)
    start = today - timedelta(days=CHECK_WINDOW_DAYS)
    try:
        closes = await asyncio.to_thread(closes_fetcher, yahoo_ticker, start, False)
    except Exception as exc:
        # yfinance is unofficial and sometimes blocked (docs/DATA-SOURCES.md).
        raise YahooUnavailableError() from exc
    if not closes:
        raise UnknownYahooSymbolError(yahoo_ticker)
    if quote_currency is None:
        try:
            quote_currency = await asyncio.to_thread(quote_currency_fetcher, yahoo_ticker)
        except Exception:
            # The closes came back, so the symbol is good; only the currency waits.
            quote_currency = None
    return InstrumentOverride(key=key, yahoo_ticker=yahoo_ticker, quote_currency=quote_currency)
