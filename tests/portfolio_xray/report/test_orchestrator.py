from datetime import date
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest

pd = pytest.importorskip("pandas")

from fin_ai_lab.core.llm.fake import FakeLlmClient  # noqa: E402
from fin_ai_lab.core.prompts.registry import PromptRegistry  # noqa: E402
from fin_ai_lab.portfolio_xray.metrics.risk import MIN_TRADING_DAYS  # noqa: E402
from fin_ai_lab.portfolio_xray.parsers.registry import ParserRegistry  # noqa: E402
from fin_ai_lab.portfolio_xray.report import orchestrator as orchestrator_module  # noqa: E402
from fin_ai_lab.portfolio_xray.report.builder import EDUCATIONAL_FOOTER  # noqa: E402
from fin_ai_lab.portfolio_xray.report.orchestrator import (  # noqa: E402
    ReportGenerationError,
    generate_report,
)
from portfolio_xray._fixtures import build_synthetic_xtb_workbook  # noqa: E402

SECTORS_PROMPTS_DIR = Path("src/fin_ai_lab/portfolio_xray/sectors/prompts")
REPORT_PROMPTS_DIR = Path("src/fin_ai_lab/portfolio_xray/report/prompts")


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(SECTORS_PROMPTS_DIR)
    registry.load_dir(REPORT_PROMPTS_DIR)
    return registry


def _covered_history() -> pd.Series:
    index = pd.date_range("2024-01-01", periods=MIN_TRADING_DAYS)
    return pd.Series([100.0 + i * 0.01 for i in range(MIN_TRADING_DAYS)], index=index)


async def test_generate_report_builds_a_faithful_report(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(ticker: str, *args: object, **kwargs: object) -> pd.Series | None:
        return _covered_history() if ticker == "ISAC.UK" else None

    monkeypatch.setattr(orchestrator_module, "fetch_price_history", fake_fetch)

    llm_client = FakeLlmClient(
        {
            "classify_sector": '{"sector": "Technology"}',
            "narrative": "Portfel jest zdywersyfikowany pomiędzy ETF i akcje.",
        }
    )

    text = await generate_report(
        build_synthetic_xtb_workbook(),
        valuation_date=date(2026, 9, 15),
        account_type="regular",
        market_currency="PLN",
        registry=ParserRegistry(),
        llm_client=llm_client,
        prompt_registry=_prompt_registry(),
        model="gemini-2.5-flash",
        openfigi_client=None,
    )

    assert text.endswith(EDUCATIONAL_FOOTER)


def _unrecognized_workbook() -> bytes:
    workbook = openpyxl.Workbook()
    workbook.active.append(["Some", "Unrelated", "Columns"])
    workbook.active.append(["a", "b", "c"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def test_generate_report_fails_when_import_has_errors() -> None:
    llm_client = FakeLlmClient({})

    with pytest.raises(ReportGenerationError):
        await generate_report(
            _unrecognized_workbook(),
            valuation_date=date(2026, 9, 15),
            account_type="regular",
            market_currency="PLN",
            registry=ParserRegistry(),
            llm_client=llm_client,
            prompt_registry=_prompt_registry(),
            model="gemini-2.5-flash",
            openfigi_client=None,
        )
