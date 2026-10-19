import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pandas as pd

# yfinance is unofficial and sometimes blocked (docs/DATA-SOURCES.md); this
# module is the only place that touches it, so risk.py stays testable
# without network. Local-only cache, never redistributed (01-story.md risk).
CACHE_DIR = Path("data/cache/prices")
LOOKBACK_CALENDAR_DAYS = 420  # margin over 250 trading days for weekends/holidays


def fetch_price_history(ticker: str, cache_dir: Path = CACHE_DIR) -> pd.Series | None:
    cache_path = cache_dir / f"{_slug(ticker)}_{date.today().isoformat()}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached["close"] is None:
            return None
        return pd.Series(cached["close"], index=pd.to_datetime(cached["dates"]))

    import yfinance as yf  # local import: numpy/pandas/yfinance are optional (extra "portfolio")

    history = yf.Ticker(ticker).history(period=f"{LOOKBACK_CALENDAR_DAYS}d")
    closes = None if history.empty else history["Close"]

    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = (
        {"dates": [], "close": None}
        if closes is None
        else {
            "dates": [d.isoformat() for d in cast(Any, closes.index).date],
            "close": closes.tolist(),
        }
    )
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return closes  # pyright: ignore[reportReturnType]


def price_change_ratio(ticker: str, since: date, cache_dir: Path = CACHE_DIR) -> Decimal | None:
    # A same-ticker ratio (latest close / close on-or-before `since`) never
    # needs to know what currency yfinance quotes the ticker in -- unlike an
    # absolute price, it can be applied directly to an already-correct,
    # already-currency-labeled stored value. See fin-ai-lab#188 for why
    # trusting an absolute foreign price at face value is a trap.
    history = fetch_price_history(ticker, cache_dir=cache_dir)
    if history is None or history.empty:
        return None
    # The most recent trading day can come back as NaN before Yahoo
    # finalizes it -- drop it rather than let it poison the ratio (same
    # dropna() risk.py already relies on for its own use of this data).
    history = history.dropna()
    if history.empty:
        return None

    closes_by_date = {cast(Any, timestamp).date(): value for timestamp, value in history.items()}
    eligible_dates = [d for d in closes_by_date if d <= since]
    if not eligible_dates:
        return None

    reference_close = closes_by_date[max(eligible_dates)]
    if reference_close == 0:
        return None

    latest_close = history.iloc[-1]
    return Decimal(str(latest_close)) / Decimal(str(reference_close))


def fetch_daily_closes(
    ticker: str,
    start: date,
    *,
    refresh: bool = False,
    adjusted: bool = False,
    cache_dir: Path = CACHE_DIR,
) -> dict[date, Decimal] | None:
    """Daily closes from `start` to today, keyed by trading date -- for a
    caller that values holdings day by day (portfolio-webapp-S10), unlike
    fetch_price_history's fixed 420-day window meant for risk metrics.

    auto_adjust=False on purpose: "Close" is then split-adjusted only, not
    dividend-adjusted, so a past day's value reads like what the position
    was actually worth that day (a dividend-adjusted close would quietly
    lower every price before each payout). `adjusted` reads "Adj Close"
    instead -- dividends reinvested, for a benchmark whose day-to-day ratio
    must include them (fin-ai-lab#273); its own cache entry. `refresh`
    skips the cache read so an explicit "odśwież" gets today's latest
    price, not the morning's."""
    kind = "daily_adjusted" if adjusted else "daily"
    cache_path = (
        cache_dir / f"{_slug(ticker)}_{start.isoformat()}_{date.today().isoformat()}_{kind}.json"
    )
    if cache_path.exists() and not refresh:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached["close"] is None:
            return None
        return {
            date.fromisoformat(d): Decimal(value)
            for d, value in zip(cached["dates"], cached["close"], strict=True)
        }

    import yfinance as yf  # local import: same reasoning as fetch_price_history

    history = yf.Ticker(ticker).history(start=start.isoformat(), auto_adjust=False)
    # Same NaN-before-finalized risk as price_change_ratio: never let it in.
    closes = None if history.empty else history["Adj Close" if adjusted else "Close"].dropna()
    if closes is not None and closes.empty:
        closes = None

    result = (
        None
        if closes is None
        else {
            cast(Any, timestamp).date(): Decimal(str(value)) for timestamp, value in closes.items()
        }
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = (
        {"dates": [], "close": None}
        if result is None
        else {
            "dates": [d.isoformat() for d in result],
            "close": [str(value) for value in result.values()],
        }
    )
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return result


def fetch_quote_currency(ticker: str, cache_dir: Path = CACHE_DIR) -> str | None:
    # Separate cache entry from fetch_price_history: a different yfinance
    # call (fast_info, not history()), and this one rarely changes, so
    # there's no reason to pay for both on every price-only lookup.
    cache_path = cache_dir / f"{_slug(ticker)}_{date.today().isoformat()}_currency.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        return cached["currency"]

    import yfinance as yf  # local import: same reasoning as fetch_price_history

    currency = yf.Ticker(ticker).fast_info.get("currency")

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"currency": currency}), encoding="utf-8")
    return currency


def fetch_dividends(ticker: str, cache_dir: Path = CACHE_DIR) -> list[tuple[date, Decimal]]:
    """Per-share dividends by ex-date, as Yahoo lists them -- in the
    listing's own quote unit (pence for a "GBp" London listing), the same
    unit as its closes (portfolio-webapp, fin-ai-lab#266). Empty both when
    the listing pays none and when Yahoo does not know the ticker: a caller
    tells the two apart by whether the ticker has closes."""
    cache_path = cache_dir / f"{_slug(ticker)}_{date.today().isoformat()}_dividends.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        return [(date.fromisoformat(day), Decimal(amount)) for day, amount in cached["dividends"]]

    import yfinance as yf  # local import: same reasoning as fetch_price_history

    series = yf.Ticker(ticker).dividends
    # value == value drops NaN, which Yahoo sometimes lists for a payout
    # it has not finalized -- same reasoning as the dropna() above.
    result = [
        (cast(Any, timestamp).date(), Decimal(str(value)))
        for timestamp, value in series.items()
        if value == value and value > 0
    ]
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {"dividends": [[day.isoformat(), str(amount)] for day, amount in result]}
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return result


# OpenFIGI's Bloomberg-style exchange code -> Yahoo Finance's own ticker
# suffix. Only the exchanges this repo's imports have actually resolved to
# are mapped (verified live: ISAC.L, ATR.WA both return real price history)
# -- same "observed data only" rule as service.py's XTB suffix table.
# NA (Euronext Amsterdam): ICHN.AS, fin-ai-lab#281.
_OPENFIGI_EXCHANGE_TO_YAHOO_SUFFIX = {"LN": "L", "PW": "WA", "NA": "AS"}


def to_yahoo_ticker(ticker: str, exchange_code: str | None) -> str:
    suffix = _OPENFIGI_EXCHANGE_TO_YAHOO_SUFFIX.get(exchange_code or "")
    return f"{ticker}.{suffix}" if suffix else ticker


def _slug(ticker: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", ticker)
