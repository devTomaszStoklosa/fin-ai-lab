from decimal import Decimal

from fin_ai_lab.market_pulse.models import IndicatorObservation
from fin_ai_lab.market_pulse.regime import classify_regime


def _obs(series_id: str, value: str, unit: str = "%") -> IndicatorObservation:
    return IndicatorObservation(
        series_id=series_id,
        label=series_id,
        value=Decimal(value),
        unit=unit,
        as_of_date="2026-09-17",
        source="fred",
    )


def test_classify_regime_flags_an_inverted_yield_curve() -> None:
    result = classify_regime([_obs("T10Y2Y", "-0.2", "p.p.")])

    assert result.regime == "risk-off"
    assert any("Krzywa" in signal for signal in result.signals)


def test_classify_regime_flags_an_elevated_vix() -> None:
    result = classify_regime([_obs("VIXCLS", "30", "pkt")])

    assert result.regime == "risk-off"
    assert any("VIX" in signal for signal in result.signals)


def test_classify_regime_is_neutral_without_signals() -> None:
    result = classify_regime([_obs("T10Y2Y", "0.5", "p.p."), _obs("VIXCLS", "15", "pkt")])

    assert result.regime == "neutral"


def test_classify_regime_is_neutral_when_indicators_are_missing() -> None:
    result = classify_regime([])

    assert result.regime == "neutral"
