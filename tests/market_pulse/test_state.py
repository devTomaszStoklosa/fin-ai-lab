from datetime import date
from decimal import Decimal

from fin_ai_lab.market_pulse.models import IndicatorObservation
from fin_ai_lab.market_pulse.state import changes_since_previous, load_previous, save_current


def _observation(value: str, series_id: str = "DGS10") -> IndicatorObservation:
    return IndicatorObservation(
        series_id=series_id, label="10Y", value=Decimal(value), unit="%",
        as_of_date=date(2026, 9, 17), source="fred",
    )


def test_save_and_load_round_trip(tmp_path) -> None:
    path = tmp_path / "state.json"
    indicators = [_observation("4.5")]

    save_current(indicators, path=path)
    loaded = load_previous(path=path)

    assert loaded == indicators


def test_load_previous_with_no_file_returns_empty_list(tmp_path) -> None:
    assert load_previous(path=tmp_path / "missing.json") == []


def test_changes_since_previous_computes_delta_for_a_matching_series() -> None:
    current = [_observation("4.6")]
    previous = [_observation("4.5")]

    updated = changes_since_previous(current, previous)

    assert updated[0].previous_value == Decimal("4.5")
    assert updated[0].change == Decimal("0.1")


def test_changes_since_previous_is_a_no_op_without_a_matching_series() -> None:
    current = [_observation("4.6")]
    previous = [_observation("4.5", series_id="DGS2")]

    updated = changes_since_previous(current, previous)

    assert updated[0].previous_value is None
    assert updated[0].change is None
