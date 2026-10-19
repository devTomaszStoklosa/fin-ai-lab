from decimal import Decimal

from fin_ai_lab.market_pulse.models import Alert, IndicatorObservation

# ASSUMPTION — starting values, not calibrated against real history yet.
# Same pattern as P2's refusal_threshold: kept explicit here, calibrated
# empirically in P3-S8's backtest (02-spec.md REQ-022, 03-design.md).
DEFAULT_THRESHOLDS: dict[str, Decimal] = {
    "DGS10": Decimal("0.10"),  # p.p. (10 bp)
    "DGS2": Decimal("0.10"),
    "T10Y2Y": Decimal("0.10"),
    "DFF": Decimal("0.05"),
    "CPIAUCSL": Decimal("1.0"),  # index points — monthly release, naturally larger jumps
    "UNRATE": Decimal("0.2"),
    "VIXCLS": Decimal("3.0"),
    "EUR/PLN": Decimal("0.02"),
    "USD/PLN": Decimal("0.02"),
    "stopa_referencyjna": Decimal("0.05"),
}


def check_alerts(
    indicators: list[IndicatorObservation], thresholds: dict[str, Decimal] = DEFAULT_THRESHOLDS
) -> list[Alert]:
    """REQ-020/021: an indicator with no configured threshold, or with no
    change yet computed (first run, or missing last time), never alerts —
    silence is a valid, expected result (AC-4), not an edge case to warn
    about."""
    alerts = []
    for observation in indicators:
        threshold = thresholds.get(observation.series_id)
        if threshold is None or observation.change is None:
            continue
        if abs(observation.change) < threshold:
            continue
        alerts.append(
            Alert(
                series_id=observation.series_id,
                previous_value=observation.previous_value,
                new_value=observation.value,
                threshold=threshold,
                message=(
                    f"{observation.label} ({observation.series_id}): "
                    f"{observation.previous_value} -> {observation.value} {observation.unit} "
                    f"(zmiana {observation.change}, próg {threshold})."
                ),
            )
        )
    return alerts
