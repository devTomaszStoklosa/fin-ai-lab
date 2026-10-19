"""XTB ticker -> what the value history needs to price it (fin-ai-lab#249).

An instrument no longer held has no row in the latest snapshot, so nothing
says where to find its quotes: the XTB symbol itself ("AAPL.US") is all there
is. Only suffixes seen in real exports are mapped; anything else (crypto and
index CFDs have no suffix at all) is reported, never guessed.
"""

# XTB suffix -> Yahoo Finance suffix ("" = none).
_YAHOO_SUFFIX = {
    "US": "",
    "UK": ".L",
    "DE": ".DE",
    "PL": ".WA",
    "FR": ".PA",
    "NL": ".AS",
    "BE": ".BR",
}

# XTB tickers whose name on Yahoo differs by more than the suffix. Each one
# seen in a real export and checked against its own lots' prices on Yahoo.
_YAHOO_RENAMES = {
    "GOOGC.US": "GOOG",  # XTB's own name for Alphabet class C
    "BRKB.US": "BRK-B",  # Berkshire class B, without the class separator
    "DOC1.US": "DOC",  # Healthpeak, on a ticker XTB had used before
    "GPOR1.US": "GPOR",  # Gulfport's shares after its 2021 bankruptcy
    "FI.US": "FISV",  # Fiserv changed ticker; Yahoo keeps it under FISV
    "NEHC.US": "NUAI",  # New Era Energy & Digital's new ticker; its 27 lots match NUAI (#281)
}

# XTB suffix -> the currencies the listing can be quoted in. One entry: the
# listing's currency. London lists the same ETF in USD, GBP or EUR, and
# Amsterdam in USD (ICHN.NL) or EUR, so it has to be told from the lot
# itself (quote_currency_from_lot).
_QUOTE_CURRENCIES = {
    "US": ("USD",),
    "PL": ("PLN",),
    "DE": ("EUR",),
    "FR": ("EUR",),
    "BE": ("EUR",),
    "UK": ("USD", "GBP", "EUR"),
    "NL": ("USD", "EUR"),
}

# How far the expected cost ratio may be off before a currency is rejected:
# NBP mid rates differ from XTB's own conversion by a fraction of a percent,
# the nearest other candidate is several percent away.
_RATIO_TOLERANCE = 0.05


def _suffix(ticker: str) -> str | None:
    base, dot, suffix = ticker.rpartition(".")
    return suffix if dot and base else None


def yahoo_symbol(ticker: str) -> str | None:
    """The Yahoo symbol of an XTB ticker, or None when the suffix is not one
    seen in real exports."""
    if ticker in _YAHOO_RENAMES:
        return _YAHOO_RENAMES[ticker]
    suffix = _suffix(ticker)
    if suffix not in _YAHOO_SUFFIX:
        return None
    return ticker.rpartition(".")[0].replace(".", "-") + _YAHOO_SUFFIX[suffix]


def candidate_quote_currencies(ticker: str) -> tuple[str, ...]:
    suffix = _suffix(ticker)
    return _QUOTE_CURRENCIES.get(suffix or "", ())


def quote_currency_from_lot(
    ticker: str,
    account_currency: str,
    cost_ratio: float,
    rate_to_account: dict[str, float],
) -> str | None:
    """The currency a listing is quoted in.

    `cost_ratio` is a lot's cost per unit in the account currency divided by
    its open price in the listing's own currency, which is exactly the
    exchange rate XTB applied: 1 when both are the account currency, about
    1.33 for a GBP-quoted ETF in a USD account. `rate_to_account` holds the
    NBP rate (currency -> account currency) for each candidate on the lot's
    open day. A single-candidate suffix needs no lot; London picks the
    nearest candidate, or None when none is within the tolerance."""
    candidates = candidate_quote_currencies(ticker)
    if len(candidates) == 1:
        return candidates[0]
    best: tuple[float, str] | None = None
    for currency in (account_currency, *candidates):
        expected = 1.0 if currency == account_currency else rate_to_account.get(currency)
        if not expected:
            continue
        error = abs(cost_ratio / expected - 1)
        if error <= _RATIO_TOLERANCE and (best is None or error < best[0]):
            best = (error, currency)
    return best[1] if best else None
