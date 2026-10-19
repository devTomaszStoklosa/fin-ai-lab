from datetime import date
from decimal import Decimal

import pytest

from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.portfolio_xray.canonical import Position
from fin_ai_lab.portfolio_xray.metrics.risk import RiskMetrics
from fin_ai_lab.portfolio_xray.metrics.weights import WeightedPosition, WeightMetrics
from fin_ai_lab.portfolio_xray.report.builder import (
    EDUCATIONAL_FOOTER,
    ReportRejectedError,
    build_report,
    verify_numbers_faithful,
)
from fin_ai_lab.portfolio_xray.report.models import InstrumentMetadata, MetricsJson


def _position(**overrides: object) -> Position:
    fields = dict(
        broker="test",
        account_type="regular",
        instrument_name="Widget Co",
        asset_class="equity",
        quantity=Decimal("1"),
        market_currency="PLN",
        valuation_date=date(2026, 9, 15),
    )
    fields.update(overrides)
    return Position(**fields)


def _metrics() -> MetricsJson:
    weights = WeightMetrics(
        weighted_positions=[
            WeightedPosition(
                position=_position(),
                weight=Decimal("0.6"),
                base_currency_value=Decimal("600"),
            ),
            WeightedPosition(
                position=_position(asset_class="etf"),
                weight=Decimal("0.4"),
                base_currency_value=Decimal("400"),
            ),
        ],
        allocation_by_asset_class={"equity": Decimal("0.6"), "etf": Decimal("0.4")},
        allocation_by_currency={"PLN": Decimal("1")},
        allocation_by_account_type={"regular": Decimal("1")},
        hhi=Decimal("0.52"),
        effective_positions=Decimal("1.92"),
        top5_share=Decimal("1"),
    )
    risk = RiskMetrics(
        coverage=0.6,
        covered_positions=1,
        total_positions=2,
        annualized_volatility=0.18,
        var_95_1d=0.02,
        max_drawdown=0.1,
        beta=1.1,
    )
    return MetricsJson(
        valuation_date=date(2026, 9, 15),
        base_currency="PLN",
        weights=weights,
        risk=risk,
        allocation_by_category={"Technology": Decimal("0.6"), "ETF/fund": Decimal("0.4")},
    )


def _prompt_registry() -> PromptRegistry:
    from pathlib import Path

    registry = PromptRegistry()
    registry.load_dir(Path("src/fin_ai_lab/portfolio_xray/report/prompts"))
    return registry


def test_verify_numbers_faithful_accepts_matching_numbers() -> None:
    metrics = _metrics()
    text = "Waga w Technology to 60%, a zmienność roczna wynosi 18%."

    assert verify_numbers_faithful(text, metrics, {}) == []


def test_verify_numbers_faithful_flags_a_fabricated_number() -> None:
    metrics = _metrics()
    text = "Zmienność roczna portfela wynosi 77%."

    mismatches = verify_numbers_faithful(text, metrics, {})

    assert mismatches == ["77%"]


def test_verify_numbers_faithful_accepts_iso_dates() -> None:
    metrics = _metrics()
    text = "Wycena na dzień 2026-09-15, waluta bazowa PLN."

    assert verify_numbers_faithful(text, metrics, {}) == []


def test_verify_numbers_faithful_accepts_the_valuation_date_written_as_polish_prose() -> None:
    metrics = _metrics()
    text = "Raport sporządzono na dzień 15 września 2026 r."

    assert verify_numbers_faithful(text, metrics, {}) == []


def test_verify_numbers_faithful_accepts_top5_share_phrased_without_a_hyphen() -> None:
    metrics = _metrics()
    text = "Udział 5 największych pozycji (top-5 share) wynosi 100%."

    assert verify_numbers_faithful(text, metrics, {}) == []


def test_verify_numbers_faithful_accepts_var_confidence_in_any_word_order() -> None:
    metrics = _metrics()
    text = "Historyczna 1-dniowa wartość zagrożona na poziomie 95% (1-day 95% VaR) to 2%."

    assert verify_numbers_faithful(text, metrics, {}) == []


def test_verify_numbers_faithful_accepts_digits_from_instrument_names() -> None:
    metrics = _metrics()
    metadata = {"0": InstrumentMetadata(name="US Treasury Bond 20+yr", category="bond")}
    text = "Portfel zawiera US Treasury Bond 20+yr."

    assert verify_numbers_faithful(text, metrics, metadata) == []


def test_verify_numbers_faithful_ignores_numbered_markdown_headings() -> None:
    metrics = _metrics()
    text = "### 3. Koncentracja portfela\nHHI wynosi 0,52."

    assert verify_numbers_faithful(text, metrics, {}) == []


def test_verify_numbers_faithful_tolerates_small_rounding() -> None:
    metrics = _metrics()
    text = "Udział top-5 to 99.7%."  # true value is 100%, within tolerance

    assert verify_numbers_faithful(text, metrics, {}) == []


async def test_build_report_appends_footer_when_model_omits_it() -> None:
    llm_client = FakeLlmClient({"narrative": "Portfel złożony w 60% z Technology i 40% z ETF."})

    text = await build_report(
        _metrics(), {}, llm_client, _prompt_registry(), "gemini-2.5-flash"
    )

    assert text.endswith(EDUCATIONAL_FOOTER)


async def test_build_report_rejects_a_report_with_fabricated_numbers() -> None:
    llm_client = FakeLlmClient({"narrative": "Zmienność roczna portfela wynosi 300%."})

    with pytest.raises(ReportRejectedError):
        await build_report(_metrics(), {}, llm_client, _prompt_registry(), "gemini-2.5-flash")


async def test_build_report_passes_instrument_metadata_key_by_position_index() -> None:
    llm_client = FakeLlmClient({"narrative": "Raport bez liczb spoza metryk."})
    metadata = {
        "0": InstrumentMetadata(name="Widget Co", category="Technology"),
        "1": InstrumentMetadata(name="Widget Co", category="ETF/fund"),
    }

    text = await build_report(
        _metrics(), metadata, llm_client, _prompt_registry(), "gemini-2.5-flash"
    )

    request = llm_client.requests[0]
    assert '"key": "0"' in request.messages[0]["text"]
    assert '"category": "Technology"' in request.messages[0]["text"]
    assert text  # sanity: no exception means verification passed
