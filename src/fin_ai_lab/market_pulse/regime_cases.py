from datetime import date
from decimal import Decimal
from typing import Protocol


class ObservationSource(Protocol):
    async def latest_observation(
        self, series_id: str, *, as_of: date | None = None
    ) -> tuple[Decimal, date] | None: ...


class MissingObservationError(ValueError):
    pass


async def build_regime_cases(scenarios: list[dict], source: ObservationSource) -> list[dict]:
    """Turns p3-regime-backtest scenarios (date, series, expected regime)
    into eval cases with the indicator values filled in from `source`.

    The values are not committed: VIXCLS is a third-party FRED series for
    learning use only (docs/DATA-SOURCES.md), so the repo keeps only the
    scenarios and each machine builds its own cases.jsonl."""
    cases = []
    for scenario in scenarios:
        as_of = date.fromisoformat(scenario["as_of_date"])
        indicators = []
        for series_id in scenario["series_ids"]:
            observation = await source.latest_observation(series_id, as_of=as_of)
            if observation is None:
                raise MissingObservationError(
                    f"{series_id} has no value on or before {as_of} (scenario {scenario['id']})"
                )
            value, _observed_on = observation
            indicators.append({"series_id": series_id, "value": str(value)})
        cases.append(
            {
                "id": scenario["id"],
                "split": scenario["split"],
                "input": {"as_of_date": scenario["as_of_date"], "indicators": indicators},
                "expected": scenario["expected"],
                "tags": scenario["tags"],
                "provenance": scenario["provenance"],
            }
        )
    return cases
