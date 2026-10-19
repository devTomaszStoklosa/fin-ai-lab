import json
from pathlib import Path

from fin_ai_lab.market_pulse.models import IndicatorObservation

# Gitignored (data/state/) — safe to delete: a missing file just means the
# next run starts without previous_value/change (03-design.md rollback note).
STATE_PATH = Path("data/state/market_pulse.json")


def load_previous(path: Path = STATE_PATH) -> list[IndicatorObservation]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [IndicatorObservation.model_validate(item) for item in data]


def save_current(indicators: list[IndicatorObservation], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [observation.model_dump(mode="json") for observation in indicators]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def changes_since_previous(
    current: list[IndicatorObservation], previous: list[IndicatorObservation]
) -> list[IndicatorObservation]:
    """REQ-012: day-over-day delta per indicator, computed in code — never
    guessed by the model. No-op (previous_value/change stay None) for a
    series with no matching entry in the previous run (first run, or a
    source that was missing last time)."""
    previous_by_series = {observation.series_id: observation for observation in previous}
    updated = []
    for observation in current:
        match = previous_by_series.get(observation.series_id)
        if match is None:
            updated.append(observation)
            continue
        updated.append(
            observation.model_copy(
                update={
                    "previous_value": match.value,
                    "change": observation.value - match.value,
                }
            )
        )
    return updated
