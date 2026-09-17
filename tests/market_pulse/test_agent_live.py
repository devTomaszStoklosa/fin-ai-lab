from pathlib import Path

import pytest

from fin_ai_lab.core.config import Settings
from fin_ai_lab.core.llm.client import GeminiLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.market_pulse.agent import ask
from fin_ai_lab.market_pulse.sources.fred import FredClient
from fin_ai_lab.market_pulse.sources.nbp import NbpClient

pytestmark = pytest.mark.live

PROMPTS_DIR = Path("src/fin_ai_lab/market_pulse/prompts")


async def test_ask_uses_afc_to_answer_with_a_real_current_value() -> None:
    settings = Settings()
    llm_client = GeminiLlmClient(settings.require_gemini_api_key())
    prompt_registry = PromptRegistry()
    prompt_registry.load_dir(PROMPTS_DIR)

    text = await ask(
        "What is the current EUR/PLN exchange rate?",
        llm_client,
        prompt_registry,
        "gemini-3.6-flash",
        FredClient(settings.require_fred_api_key()),
        NbpClient(),
    )

    assert text.strip() != ""
