import json
import re
from decimal import Decimal

from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.portfolio_xray.report.models import InstrumentMetadata, MetricsJson

# REQ-041 tolerance: relative (matches the 0.5% already used for the portfolio
# sum check in 02-spec.md) with an absolute floor so metrics near zero (e.g.
# 0% volatility) aren't compared with an effectively-zero tolerance.
RELATIVE_TOLERANCE = Decimal("0.005")
ABSOLUTE_TOLERANCE_FLOOR = Decimal("0.05")

EDUCATIONAL_FOOTER = (
    "---\n"
    "Ten raport jest analizą edukacyjną, nie rekomendacją inwestycyjną. Nie stanowi porady "
    "inwestycyjnej w rozumieniu MiFID II i nie jest sugestią kupna, sprzedaży ani zmiany "
    "alokacji. Decyzje inwestycyjne podejmujesz na własną odpowiedzialność."
)

# Fixed methodology parameters, not computed values — they can appear in the
# text in any wording ("top-5", "5 największych pozycji", "95%", "na poziomie
# 95%", "1-day 95% VaR"...) so they're accepted as reference values below
# rather than pattern-matched as text.
_TOP_N_SHARE = 5  # weights.TOP_N_SHARE
_VAR_CONFIDENCE_PERCENT = 95  # risk.py's fixed VaR confidence level

_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])-?\d[\d  ]*(?:[.,]\d+)?%?")
_DIGITS_RE = re.compile(r"\d+")
# Markdown section numbering ("### 3. Koncentracja portfela") is structure,
# not data — strip the ordinal before scanning for numbers.
_HEADING_ORDINAL_RE = re.compile(r"^#{1,6}\s*\d+[.)]\s+", re.MULTILINE)


class ReportRejectedError(Exception):
    def __init__(self, mismatches: list[str]) -> None:
        super().__init__(f"Report rejected, numbers not faithful to metrics: {mismatches}")
        self.mismatches = mismatches


async def build_report(
    metrics: MetricsJson,
    instrument_metadata: dict[str, InstrumentMetadata],
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
) -> str:
    payload = _metrics_payload(metrics, instrument_metadata)
    prompt = prompt_registry.get("narrative", 2)
    rendered = prompt.render(metrics_json=_to_json(payload))

    request = LlmRequest(
        model=model,
        messages=[{"role": "user", "text": rendered}],
        prompt_id="narrative",
        prompt_version=2,
    )
    result = await llm_client.complete(request)
    text = result.text.strip()
    if EDUCATIONAL_FOOTER not in text:
        text = f"{text}\n\n{EDUCATIONAL_FOOTER}"

    mismatches = verify_numbers_faithful(text, metrics, instrument_metadata)
    if mismatches:
        raise ReportRejectedError(mismatches)
    return text


def verify_numbers_faithful(
    report_text: str,
    metrics: MetricsJson,
    instrument_metadata: dict[str, InstrumentMetadata],
) -> list[str]:
    candidates = _reference_values(metrics, instrument_metadata)
    cleaned_text = _HEADING_ORDINAL_RE.sub("", report_text)

    mismatches: list[str] = []
    for raw_match in _NUMBER_RE.findall(cleaned_text):
        value = _parse_number(raw_match)
        if value is None:
            continue
        if not any(_within_tolerance(value, candidate) for candidate in candidates):
            mismatches.append(raw_match.strip())
    return mismatches


def _metrics_payload(
    metrics: MetricsJson, instrument_metadata: dict[str, InstrumentMetadata]
) -> dict:
    positions = []
    for index, weighted in enumerate(metrics.weights.weighted_positions):
        key = str(index)
        meta = instrument_metadata.get(key)
        positions.append(
            {
                "key": key,
                "weight": str(weighted.weight),
                "base_currency_value": str(weighted.base_currency_value),
                "instrument": meta.model_dump() if meta is not None else None,
            }
        )

    return {
        "valuation_date": metrics.valuation_date.isoformat(),
        "base_currency": metrics.base_currency,
        "positions": positions,
        "hhi": str(metrics.weights.hhi),
        "effective_positions": str(metrics.weights.effective_positions),
        "top5_share": str(metrics.weights.top5_share),
        "allocation_by_asset_class": _stringify(metrics.weights.allocation_by_asset_class),
        "allocation_by_currency": _stringify(metrics.weights.allocation_by_currency),
        "allocation_by_account_type": _stringify(metrics.weights.allocation_by_account_type),
        "allocation_by_category": _stringify(metrics.allocation_by_category),
        "risk": metrics.risk.model_dump() if metrics.risk is not None else None,
    }


def _stringify(values: dict[str, Decimal]) -> dict[str, str]:
    return {key: str(value) for key, value in values.items()}


def _to_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _reference_values(
    metrics: MetricsJson, instrument_metadata: dict[str, InstrumentMetadata]
) -> list[Decimal]:
    leaves: list[Decimal] = []
    _collect_numeric_leaves(metrics.model_dump(mode="json"), leaves)

    candidates: list[Decimal] = []
    for leaf in leaves:
        candidates.append(leaf)
        candidates.append(leaf * 100)  # fractions are often rendered as percentages

    candidates.append(Decimal(_TOP_N_SHARE))
    candidates.append(Decimal(_VAR_CONFIDENCE_PERCENT))
    candidates.append(Decimal(_VAR_CONFIDENCE_PERCENT) / 100)

    # The valuation date can be written in any locale form ("15 września
    # 2026", "15.09.2026"...) — accept its parts instead of pattern-matching
    # every possible rendering.
    candidates.append(Decimal(metrics.valuation_date.day))
    candidates.append(Decimal(metrics.valuation_date.month))
    candidates.append(Decimal(metrics.valuation_date.year))

    # Instrument names are given data, quoted verbatim, not computed values —
    # a digit inside one (e.g. "US Treasury Bond 20+yr") isn't a fabrication.
    for meta in instrument_metadata.values():
        for digits in _DIGITS_RE.findall(meta.name):
            candidates.append(Decimal(digits))

    return candidates


def _collect_numeric_leaves(value: object, out: list[Decimal]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        out.append(Decimal(str(value)))
    elif isinstance(value, str):
        try:
            out.append(Decimal(value))
        except Exception:
            pass
    elif isinstance(value, dict):
        for item in value.values():
            _collect_numeric_leaves(item, out)
    elif isinstance(value, list):
        for item in value:
            _collect_numeric_leaves(item, out)


def _parse_number(raw: str) -> Decimal | None:
    text = raw.strip()
    is_percent = text.endswith("%")
    text = text.rstrip("%").strip()
    text = text.replace(" ", "").replace(" ", "")

    if "," in text and "." in text:
        text = text.replace(",", "")  # comma is a thousands separator here
    elif "," in text:
        text = text.replace(",", ".")  # comma is the decimal separator here

    try:
        value = Decimal(text)
    except Exception:
        return None
    return value / 100 if is_percent else value


def _within_tolerance(value: Decimal, candidate: Decimal) -> bool:
    diff = abs(value - candidate)
    tolerance = max(RELATIVE_TOLERANCE * abs(candidate), ABSOLUTE_TOLERANCE_FLOOR)
    return diff <= tolerance
