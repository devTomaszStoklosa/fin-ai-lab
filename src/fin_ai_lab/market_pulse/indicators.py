import asyncio

import httpx

from fin_ai_lab.market_pulse.models import IndicatorObservation
from fin_ai_lab.market_pulse.sources.fred import FredClient
from fin_ai_lab.market_pulse.sources.nbp import NbpClient, fetch_reference_rate

# (label, unit) — public-domain FRED series (docs/DATA-SOURCES.md "FRED —
# licencja per seria"); VIXCLS (third-party licensed, learning use only)
# included since this repo never redistributes the brief.
DEFAULT_FRED_SERIES: dict[str, tuple[str, str]] = {
    "DGS10": ("Rentowność 10-letnich obligacji USA", "%"),
    "DGS2": ("Rentowność 2-letnich obligacji USA", "%"),
    "T10Y2Y": ("Spread 10Y-2Y (krzywa rentowności)", "p.p."),
    "DFF": ("Stopa funduszy federalnych (efektywna)", "%"),
    "CPIAUCSL": ("CPI (inflacja USA)", "indeks 1982-84=100"),
    "UNRATE": ("Stopa bezrobocia USA", "%"),
    "VIXCLS": ("VIX", "pkt"),
}

DEFAULT_NBP_FX_CODES: dict[str, str] = {
    "EUR": "EUR/PLN",
    "USD": "USD/PLN",
}


async def fetch_indicators(
    fred_client: FredClient, nbp_client: NbpClient
) -> tuple[list[IndicatorObservation], list[str]]:
    """Fetches every configured indicator concurrently (P3-S4:
    orchestrator-workers — this is the orchestrator's parallel-fetch
    stage, docs/LEARNING.md glossary). A source that fails (network
    error, non-2xx) or has nothing published yet is skipped and listed as
    missing (REQ-002/013) instead of failing the whole run."""

    async def fred_task(series_id: str, label: str, unit: str) -> IndicatorObservation | str:
        try:
            result = await fred_client.latest_observation(series_id)
        except httpx.HTTPError:
            result = None
        if result is None:
            return f"fred:{series_id}"
        value, as_of = result
        return IndicatorObservation(
            series_id=series_id, label=label, value=value, unit=unit,
            as_of_date=as_of, source="fred",
        )

    async def nbp_fx_task(code: str, label: str) -> IndicatorObservation | str:
        try:
            result = await nbp_client.fetch_fx_rate(code)
        except httpx.HTTPError:
            result = None
        if result is None:
            return f"nbp-fx:{code}"
        value, as_of = result
        return IndicatorObservation(
            series_id=f"{code}/PLN", label=label, value=value, unit="PLN",
            as_of_date=as_of, source="nbp-fx",
        )

    async def nbp_rate_task() -> IndicatorObservation | str:
        try:
            value, as_of = await fetch_reference_rate()
        except httpx.HTTPError:
            return "nbp-rate:stopa_referencyjna"
        return IndicatorObservation(
            series_id="stopa_referencyjna", label="Stopa referencyjna NBP",
            value=value, unit="%", as_of_date=as_of, source="nbp-rate",
        )

    fred_tasks = [
        fred_task(series_id, label, unit)
        for series_id, (label, unit) in DEFAULT_FRED_SERIES.items()
    ]
    nbp_fx_tasks = [nbp_fx_task(code, label) for code, label in DEFAULT_NBP_FX_CODES.items()]
    tasks = fred_tasks + nbp_fx_tasks + [nbp_rate_task()]
    results = await asyncio.gather(*tasks)

    observations = [result for result in results if isinstance(result, IndicatorObservation)]
    missing = [result for result in results if isinstance(result, str)]
    return observations, missing
