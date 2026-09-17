import json
from datetime import date
from decimal import Decimal
from pathlib import Path

# yfinance is unofficial and sometimes blocked (docs/DATA-SOURCES.md); WIG20
# is available only through the MCP server's interactive tool (P3-S3,
# 03-design.md open question #1), never the automated brief. Sync, not
# async — matches the existing yfinance usage in
# portfolio_xray/metrics/price_history.py, blocking is fine here because the
# MCP stdio transport serves one request at a time.
CACHE_DIR = Path("data/cache/prices")
WIG20_TICKER = "WIG20.WA"  # verified live against Yahoo Finance, 2026-09-17


def fetch_wig20(cache_dir: Path = CACHE_DIR) -> tuple[Decimal, date] | None:
    today = date.today()
    cache_path = cache_dir / f"wig20_{today.isoformat()}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached["value"] is None:
            return None
        return Decimal(cached["value"]), date.fromisoformat(cached["as_of"])

    import yfinance as yf  # local import: optional (extra "pulse")

    history = yf.Ticker(WIG20_TICKER).history(period="5d")
    result = (
        None
        if history.empty
        else (Decimal(str(history["Close"].iloc[-1])), history.index[-1].date())
    )

    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = (
        {"value": None, "as_of": None}
        if result is None
        else {"value": str(result[0]), "as_of": result[1].isoformat()}
    )
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return result
