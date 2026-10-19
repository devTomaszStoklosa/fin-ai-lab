from datetime import date, timedelta
from decimal import Decimal

import httpx

from fin_ai_lab.core.http.client import ThrottledHttpClient

NBP_BASE_URL = "https://api.nbp.pl"

# NBP rejects a date-range query longer than 93 days (api.nbp.pl/en.html).
# Windows are aligned to a fixed epoch rather than to the caller's own start
# date, so every fully-past window has the exact same URL on every call and
# stays a permanent cache hit (ThrottledHttpClient caches by request); only
# the window containing today changes from one day to the next.
SERIES_WINDOW_DAYS = 90
_SERIES_EPOCH = date(2000, 1, 3)


async def fetch_nbp_rate(
    http_client: ThrottledHttpClient,
    *,
    table: str,
    code: str,
    as_of: date,
    max_lookback_days: int,
) -> tuple[Decimal, date] | None:
    """Mid rate for `code` from NBP table `table` (dated request, not the
    "currently in effect" endpoint, so each day's answer is a permanently
    valid cache entry). Walks back day by day from `as_of` when a day has
    no published table (weekends/holidays), up to `max_lookback_days`.
    Returns (rate, effective_date) or None once the window is exhausted --
    shared by portfolio_xray.metrics.fx.NbpFxClient and
    market_pulse.sources.nbp.NbpClient, which differ in table set,
    lookback window and not-found behavior (issue #63)."""
    current_date = as_of
    for _ in range(max_lookback_days):
        path = f"/api/exchangerates/rates/{table}/{code.lower()}/{current_date.isoformat()}/"
        try:
            response = await http_client.get(path, params={"format": "json"})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                current_date -= timedelta(days=1)
                continue
            raise
        rate = response["rates"][0]
        effective_date = (
            date.fromisoformat(rate["effectiveDate"])
            if "effectiveDate" in rate
            else current_date
        )
        return Decimal(str(rate["mid"])), effective_date
    return None


async def fetch_nbp_rate_series(
    http_client: ThrottledHttpClient,
    *,
    table: str,
    code: str,
    start: date,
    end: date,
) -> dict[date, Decimal]:
    """Every published mid rate for `code` in [start, end], keyed by its
    effective date -- one request per SERIES_WINDOW_DAYS window instead of
    one per day, for a caller that values something day by day over months
    (portfolio-webapp-S10). Days without a table (weekends/holidays) are
    simply absent; filling them is the caller's decision, not this one's.
    A window with no table at all answers 404 -- an empty window, not an
    error."""
    rates: dict[date, Decimal] = {}
    window_start = _SERIES_EPOCH + timedelta(
        days=((start - _SERIES_EPOCH).days // SERIES_WINDOW_DAYS) * SERIES_WINDOW_DAYS
    )
    while window_start <= end:
        window_end = window_start + timedelta(days=SERIES_WINDOW_DAYS - 1)
        query_end = min(window_end, end)
        path = (
            f"/api/exchangerates/rates/{table}/{code.lower()}/"
            f"{window_start.isoformat()}/{query_end.isoformat()}/"
        )
        try:
            response = await http_client.get(path, params={"format": "json"})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            response = {"rates": []}
        for rate in response["rates"]:
            effective_date = date.fromisoformat(rate["effectiveDate"])
            if start <= effective_date <= end:
                rates[effective_date] = Decimal(str(rate["mid"]))
        window_start = window_end + timedelta(days=1)
    return rates
