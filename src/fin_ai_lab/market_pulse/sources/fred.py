from datetime import date
from decimal import Decimal

from fin_ai_lab.core.http.client import ThrottledHttpClient

FRED_BASE_URL = "https://api.stlouisfed.org"
# 120 req/min free tier (docs/DATA-SOURCES.md) — well under it for a
# handful of series per run, kept conservative anyway.
DEFAULT_MIN_INTERVAL_S = 1.0


class FredClient:
    def __init__(
        self, api_key: str, *, http_client: ThrottledHttpClient | None = None
    ) -> None:
        self._api_key = api_key
        self._http = http_client or ThrottledHttpClient(
            FRED_BASE_URL, min_interval_s=DEFAULT_MIN_INTERVAL_S, provider="fred"
        )

    async def latest_observation(
        self, series_id: str, *, as_of: date | None = None
    ) -> tuple[Decimal, date] | None:
        """Latest published value for a FRED series on or before `as_of`
        (today by default). `observation_end` bounds the query to that
        date, which — unlike an unbounded "give me the latest" query — also
        makes the disk cache correct: the same request made on a later day
        asks a different question and gets its own cache entry, instead of
        forever returning whatever was cached first."""
        as_of = as_of or date.today()
        data = await self._http.get(
            "/fred/series/observations",
            params={
                "series_id": series_id,
                "api_key": self._api_key,
                "file_type": "json",
                "observation_end": as_of.isoformat(),
                "sort_order": "desc",
                "limit": 1,
            },
        )
        observations = data.get("observations", [])
        if not observations or observations[0]["value"] == ".":
            return None

        observation = observations[0]
        return Decimal(observation["value"]), date.fromisoformat(observation["date"])
