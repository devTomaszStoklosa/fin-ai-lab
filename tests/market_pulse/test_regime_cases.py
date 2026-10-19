from datetime import date
from decimal import Decimal

import pytest

from fin_ai_lab.market_pulse.regime_cases import MissingObservationError, build_regime_cases

SCENARIO = {
    "id": "spike-2020-03-16",
    "split": "dev",
    "as_of_date": "2020-03-16",
    "series_ids": ["VIXCLS", "T10Y2Y"],
    "expected": {"regime": "risk-off"},
    "tags": ["vix-spike"],
    "provenance": "human",
}


class FakeSource:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values
        self.requests: list[tuple[str, date | None]] = []

    async def latest_observation(
        self, series_id: str, *, as_of: date | None = None
    ) -> tuple[Decimal, date] | None:
        self.requests.append((series_id, as_of))
        value = self._values.get(series_id)
        return (Decimal(value), as_of) if value is not None and as_of is not None else None


async def test_build_regime_cases_fills_each_indicator_value_for_the_scenario_date() -> None:
    source = FakeSource({"VIXCLS": "50.5", "T10Y2Y": "0.25"})

    cases = await build_regime_cases([SCENARIO], source)

    assert cases == [
        {
            "id": "spike-2020-03-16",
            "split": "dev",
            "input": {
                "as_of_date": "2020-03-16",
                "indicators": [
                    {"series_id": "VIXCLS", "value": "50.5"},
                    {"series_id": "T10Y2Y", "value": "0.25"},
                ],
            },
            "expected": {"regime": "risk-off"},
            "tags": ["vix-spike"],
            "provenance": "human",
        }
    ]
    assert source.requests == [
        ("VIXCLS", date(2020, 3, 16)),
        ("T10Y2Y", date(2020, 3, 16)),
    ]


async def test_build_regime_cases_fails_when_a_series_has_no_value() -> None:
    source = FakeSource({"VIXCLS": "50.5"})

    with pytest.raises(MissingObservationError, match="T10Y2Y"):
        await build_regime_cases([SCENARIO], source)
