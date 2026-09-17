from datetime import date, timedelta
from decimal import Decimal
from xml.etree import ElementTree

import httpx

from fin_ai_lab.core.http.client import ThrottledHttpClient

NBP_BASE_URL = "https://api.nbp.pl"
NBP_RATES_URL = "https://static.nbp.pl/dane/stopy/stopy_procentowe.xml"
# No published limit ("zachowaj umiar", docs/DATA-SOURCES.md) — kept
# conservative anyway.
DEFAULT_MIN_INTERVAL_S = 1.0
# Weekends and holidays have no published rate table — walk back far
# enough to cross a long weekend, not indefinitely.
MAX_LOOKBACK_DAYS = 10


class NbpClient:
    def __init__(self, *, fx_http_client: ThrottledHttpClient | None = None) -> None:
        self._fx = fx_http_client or ThrottledHttpClient(
            NBP_BASE_URL, min_interval_s=DEFAULT_MIN_INTERVAL_S, provider="nbp-fx"
        )

    async def fetch_fx_rate(
        self, code: str, *, as_of: date | None = None
    ) -> tuple[Decimal, date] | None:
        """Mid rate (table A) for a currency, on or before `as_of` (today
        by default). Walks back day by day until a published table is
        found — a dated request (not the "currently in effect" endpoint)
        so each day's answer is its own, permanently valid cache entry."""
        as_of = as_of or date.today()
        for offset in range(MAX_LOOKBACK_DAYS):
            day = as_of - timedelta(days=offset)
            try:
                data = await self._fx.get(
                    f"/api/exchangerates/rates/a/{code.lower()}/{day.isoformat()}/"
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    continue
                raise
            rate = data["rates"][0]
            return Decimal(str(rate["mid"])), date.fromisoformat(rate["effectiveDate"])
        return None


async def fetch_reference_rate() -> tuple[Decimal, date]:
    """The NBP reference rate, read straight from NBP's own live snapshot
    (static.nbp.pl/dane/stopy/stopy_procentowe.xml) — not api.nbp.pl, which
    only covers FX/gold (03-design.md, resolved open question #2).

    Deliberately bypasses ThrottledHttpClient's disk cache: this file
    always reflects "the currently effective rate", not an immutable
    historical fact for a given date, so caching it would silently keep
    returning a stale rate after every future change (the rate itself
    changes only a few times a year, but a run must never guess it's
    unchanged — it must read the current value each time)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(NBP_RATES_URL)
    response.raise_for_status()

    root = ElementTree.fromstring(response.content)
    reference = root.find(".//pozycja[@id='ref']")
    if reference is None:
        raise ValueError("NBP reference rate not found in stopy_procentowe.xml")

    value = Decimal(reference.attrib["oprocentowanie"].replace(",", "."))
    as_of = date.fromisoformat(reference.attrib["obowiazuje_od"])
    return value, as_of
