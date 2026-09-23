from datetime import date, timedelta
from decimal import Decimal

import httpx

from fin_ai_lab.core.http.client import ThrottledHttpClient

NBP_BASE_URL = "https://api.nbp.pl"


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
