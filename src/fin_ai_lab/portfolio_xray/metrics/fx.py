from datetime import date
from decimal import Decimal

from fin_ai_lab.core.data.nbp import NBP_BASE_URL, fetch_nbp_rate
from fin_ai_lab.core.http.client import ThrottledHttpClient

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
        result = await fetch_nbp_rate(
            self._http_client,
            table=table,
            code=currency,
            as_of=as_of,
            max_lookback_days=MAX_LOOKBACK_DAYS,
        )
        return result[0] if result is not None else None


async def convert_to_base_currency(
    amount: Decimal, currency: str, valuation_date: date, fx_client: NbpFxClient
) -> Decimal:
    rate = await fx_client.mid_rate(currency, valuation_date)
    return amount * rate
