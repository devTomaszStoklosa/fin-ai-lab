import json
import re
from datetime import date
from pathlib import Path

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
        else {"dates": [d.isoformat() for d in closes.index.date], "close": closes.tolist()}
    )
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return closes


def _slug(ticker: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", ticker)
