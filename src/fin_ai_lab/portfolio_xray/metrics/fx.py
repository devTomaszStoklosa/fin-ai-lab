from datetime import date, timedelta
from decimal import Decimal

import httpx

from fin_ai_lab.core.http.client import ThrottledHttpClient

NBP_BASE_URL = "https://api.nbp.pl"
# NBP docs (api.nbp.pl/en.html, verified 2026-09-16) state no explicit rate
# limit ("zachowaj umiar" per docs/DATA-SOURCES.md) — this is our own,
# deliberately modest choice, not a documented threshold.
DEFAULT_MIN_INTERVAL_S = 0.5
MAX_LOOKBACK_DAYS = 7  # covers long weekends/holidays without table A or B


class FxRateNotFoundError(Exception):
    pass


class NbpFxClient:
    def __init__(self, http_client: ThrottledHttpClient | None = None) -> None:
        self._http_client = http_client or ThrottledHttpClient(
            NBP_BASE_URL, min_interval_s=DEFAULT_MIN_INTERVAL_S, provider="nbp"
        )

    async def mid_rate(self, currency: str, as_of: date) -> Decimal:
        if currency == "PLN":
            return Decimal(1)

        for table in ("a", "b"):
            rate = await self._rate_from_table(table, currency, as_of)
            if rate is not None:
                return rate

        raise FxRateNotFoundError(
            f"No NBP table A or B rate for '{currency}' on or before {as_of.isoformat()}"
        )

    async def _rate_from_table(self, table: str, currency: str, as_of: date) -> Decimal | None:
        current_date = as_of
        for _ in range(MAX_LOOKBACK_DAYS):
            path = (
                f"/api/exchangerates/rates/{table}/{currency.lower()}"
                f"/{current_date.isoformat()}/"
            )
            try:
                response = await self._http_client.get(path, params={"format": "json"})
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    current_date -= timedelta(days=1)
                    continue
                raise
            return Decimal(str(response["rates"][0]["mid"]))
        return None


async def convert_to_base_currency(
    amount: Decimal, currency: str, valuation_date: date, fx_client: NbpFxClient
) -> Decimal:
    rate = await fx_client.mid_rate(currency, valuation_date)
    return amount * rate
