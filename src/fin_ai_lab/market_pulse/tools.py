from collections.abc import Callable

from fin_ai_lab.market_pulse.sources.fred import FredClient
from fin_ai_lab.market_pulse.sources.nbp import NbpClient, fetch_reference_rate


def build_tools(fred_client: FredClient, nbp_client: NbpClient) -> list[Callable]:
    """Tools for the model's automatic function calling (AFC, P3-S2,
    03-design.md) — the agent decides which of these to call, instead of
    P3-S1's fixed indicator list. Docstrings and type hints are what the
    SDK uses to build each tool's schema for the model, so they're written
    for the model to read, not just for a human."""

    async def get_fred_series_value(series_id: str) -> str:
        """Get the latest published value of a US macro/rate indicator
        from FRED (Federal Reserve Economic Data).

        Common series_id values: "DGS10" (10-year Treasury yield),
        "DGS2" (2-year Treasury yield), "T10Y2Y" (10Y-2Y yield spread),
        "DFF" (effective federal funds rate), "CPIAUCSL" (CPI index),
        "UNRATE" (unemployment rate), "VIXCLS" (VIX volatility index).

        Args:
            series_id: The FRED series ID to look up.
        """
        result = await fred_client.latest_observation(series_id)
        if result is None:
            return f"No recent value published for FRED series '{series_id}'."
        value, as_of = result
        return f"{series_id} = {value}, as of {as_of.isoformat()}."

    async def get_nbp_fx_rate(currency_code: str) -> str:
        """Get the latest NBP mid exchange rate for a foreign currency
        against the Polish zloty (PLN).

        Args:
            currency_code: ISO 4217 currency code, e.g. "EUR" or "USD".
        """
        result = await nbp_client.fetch_fx_rate(currency_code)
        if result is None:
            return f"No recent NBP rate published for '{currency_code}'."
        value, as_of = result
        return f"{currency_code}/PLN = {value}, as of {as_of.isoformat()}."

    async def get_nbp_reference_rate() -> str:
        """Get the National Bank of Poland's (NBP) current reference
        interest rate — the main policy rate."""
        value, as_of = await fetch_reference_rate()
        return f"NBP reference rate = {value}%, in effect since {as_of.isoformat()}."

    return [get_fred_series_value, get_nbp_fx_rate, get_nbp_reference_rate]
