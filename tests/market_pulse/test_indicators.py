from datetime import date
from decimal import Decimal

import httpx

from fin_ai_lab.market_pulse.indicators import (
    DEFAULT_FRED_SERIES,
    DEFAULT_NBP_FX_CODES,
    fetch_indicators,
)


class _FakeFredClient:
    def __init__(self, values: dict[str, tuple[Decimal, date] | None] | None = None) -> None:
        self._values = values or {}

    async def latest_observation(self, series_id: str):
        if series_id not in self._values:
            raise httpx.HTTPError("boom")
        return self._values[series_id]


class _FakeNbpClient:
    def __init__(self, values: dict[str, tuple[Decimal, date] | None] | None = None) -> None:
        self._values = values or {}

    async def fetch_fx_rate(self, code: str):
        return self._values.get(code)


async def test_fetch_indicators_returns_observations_for_available_sources(
    monkeypatch,
) -> None:
    fred_values = {
        series_id: (Decimal("1"), date(2026, 9, 17)) for series_id in DEFAULT_FRED_SERIES
    }
    fred = _FakeFredClient(fred_values)
    nbp_values = {code: (Decimal("4.3"), date(2026, 9, 17)) for code in DEFAULT_NBP_FX_CODES}
    nbp = _FakeNbpClient(nbp_values)

    async def fake_reference_rate():
        return Decimal("3.75"), date(2026, 3, 5)

    monkeypatch.setattr(
        "fin_ai_lab.market_pulse.indicators.fetch_reference_rate", fake_reference_rate
    )

    observations, missing = await fetch_indicators(fred, nbp)

    assert missing == []
    assert len(observations) == len(DEFAULT_FRED_SERIES) + len(DEFAULT_NBP_FX_CODES) + 1
    assert any(observation.series_id == "stopa_referencyjna" for observation in observations)


async def test_fetch_indicators_lists_a_failed_source_as_missing_not_a_crash(monkeypatch) -> None:
    fred = _FakeFredClient({})  # every series raises
    nbp = _FakeNbpClient({})  # every code returns None (not published)

    async def fake_reference_rate():
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(
        "fin_ai_lab.market_pulse.indicators.fetch_reference_rate", fake_reference_rate
    )

    observations, missing = await fetch_indicators(fred, nbp)

    assert observations == []
    assert len(missing) == len(DEFAULT_FRED_SERIES) + len(DEFAULT_NBP_FX_CODES) + 1
