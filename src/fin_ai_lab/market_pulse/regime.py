from decimal import Decimal

from fin_ai_lab.market_pulse.models import IndicatorObservation, RegimeResult

# ASSUMPTION (03-design.md "regime.classify_regime — reguła"): starting
# thresholds, not measured against real history — calibrate in the P3-S8
# backtest before trusting them, same pattern as P2's refusal_threshold.
# Matches 02-spec.md's business-rule table exactly: it only describes
# risk-off tilts and "no signal -> neutral", no risk-on trigger yet.
VIX_RISK_OFF_THRESHOLD = Decimal("25")
YIELD_CURVE_INVERTED_THRESHOLD = Decimal("0")


def classify_regime(indicators: list[IndicatorObservation]) -> RegimeResult:
    """Deterministic, code-computed classification (REQ-010) — the model
    never decides the label, only explains a result already computed
    here."""
    by_series = {observation.series_id: observation for observation in indicators}
    signals: list[str] = []

    curve = by_series.get("T10Y2Y")
    if curve is not None and curve.value <= YIELD_CURVE_INVERTED_THRESHOLD:
        signals.append(f"Krzywa rentowności odwrócona (T10Y2Y = {curve.value} {curve.unit})")

    vix = by_series.get("VIXCLS")
    if vix is not None and vix.value >= VIX_RISK_OFF_THRESHOLD:
        signals.append(f"VIX podwyższony (VIX = {vix.value})")

    if signals:
        return RegimeResult(regime="risk-off", signals=signals)
    return RegimeResult(regime="neutral", signals=["Brak sygnałów przekraczających próg"])
