import json
from datetime import date
from pathlib import Path

import pytest

from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.portfolio_xray.parsers.correction import (
    CorrectionLoopError,
    propose_and_validate_config,
    render_masked_sample,
)

PROMPTS_DIR = Path("src/fin_ai_lab/portfolio_xray/parsers/prompts")


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


def _proposal_json(**overrides: object) -> str:
    body = {
        "sheet_name": "Positions",
        "header_row": 1,
        "row_filter": None,
        "expected_headers": ["Name", "Qty", "Price"],
        "column_mapping": [
            {"file_header": "Name", "field": "instrument_name"},
            {"file_header": "Qty", "field": "quantity"},
            {"file_header": "Price", "field": "avg_cost"},
        ],
        "number_format": "en",
        "date_format": "%Y-%m-%d",
        "encoding": "utf-8",
        "delimiter": None,
    }
    body.update(overrides)
    return json.dumps(body)


def _sheets(rows: list[tuple]) -> dict[str, list[tuple]]:
    return {"Positions": rows}


def test_render_masked_sample_keeps_headers_masks_pii_values() -> None:
    sheets = _sheets(
        [
            ("Imię i nazwisko", "Ticker", "Volume"),
            ("Jan Kowalski", "ISAC.UK", 6),
        ]
    )

    rendered = render_masked_sample(sheets)

    assert "Imię i nazwisko" in rendered  # header label stays visible
    assert "Jan Kowalski" not in rendered  # value under it is masked
    assert "[MASKED]" in rendered
    assert "ISAC.UK" in rendered  # non-PII column untouched


async def test_propose_and_validate_config_succeeds_on_first_try() -> None:
    sheets = _sheets([("Name", "Qty", "Price"), ("Widget Co", 10, "5.5")])
    llm_client = FakeLlmClient({"propose_config": _proposal_json()})

    config, positions = await propose_and_validate_config(
        llm_client,
        _prompt_registry(),
        "gemini-2.5-flash",
        sheets,
        broker="newbroker",
        version=1,
        account_type="regular",
        market_currency="PLN",
        valuation_date=date(2026, 9, 15),
    )

    assert config.broker == "newbroker"
    assert len(positions) == 1
    assert len(llm_client.requests) == 1


async def test_propose_and_validate_config_retries_on_validation_error() -> None:
    # quantity 0 fails Position validation no matter what the model proposes,
    # so this always exhausts the correction loop.
    sheets = _sheets([("Name", "Qty", "Price"), ("Widget Co", 0, "5.5")])
    llm_client = FakeLlmClient({"propose_config": _proposal_json()})

    with pytest.raises(CorrectionLoopError):
        await propose_and_validate_config(
            llm_client,
            _prompt_registry(),
            "gemini-2.5-flash",
            sheets,
            broker="newbroker",
            version=1,
            account_type="regular",
            market_currency="PLN",
            valuation_date=date(2026, 9, 15),
        )

    assert len(llm_client.requests) == 3  # 1 initial attempt + 2 corrections
