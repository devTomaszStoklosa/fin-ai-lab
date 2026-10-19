from datetime import date
from decimal import Decimal

from fin_ai_lab.market_pulse.alerts import check_alerts
from fin_ai_lab.market_pulse.models import IndicatorObservation


def _observation(
    value: str, previous_value: str | None, change: str | None, series_id: str = "DGS10"
) -> IndicatorObservation:
    return IndicatorObservation(
        series_id=series_id, label="10Y", value=Decimal(value), unit="%",
        as_of_date=date(2026, 9, 17), source="fred",
        previous_value=Decimal(previous_value) if previous_value else None,
        change=Decimal(change) if change else None,
    )


def test_check_alerts_fires_when_change_crosses_threshold() -> None:
    observation = _observation("4.7", "4.5", "0.2")

    alerts = check_alerts([observation], thresholds={"DGS10": Decimal("0.10")})

    assert len(alerts) == 1
    assert alerts[0].series_id == "DGS10"
    assert alerts[0].previous_value == Decimal("4.5")
    assert alerts[0].new_value == Decimal("4.7")


def test_check_alerts_is_silent_when_change_is_below_threshold() -> None:
    observation = _observation("4.55", "4.5", "0.05")

    alerts = check_alerts([observation], thresholds={"DGS10": Decimal("0.10")})

    assert alerts == []


def test_check_alerts_is_silent_without_a_previous_value() -> None:
    observation = _observation("4.5", None, None)

    alerts = check_alerts([observation], thresholds={"DGS10": Decimal("0.10")})

    assert alerts == []


def test_check_alerts_is_silent_for_a_series_with_no_configured_threshold() -> None:
    observation = _observation("100.0", "1.0", "99.0", series_id="CPIAUCSL")

    alerts = check_alerts([observation], thresholds={"DGS10": Decimal("0.10")})

    assert alerts == []
