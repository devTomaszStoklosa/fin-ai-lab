from pathlib import Path

from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.market_pulse.agent import ask
from fin_ai_lab.market_pulse.sources.fred import FredClient
from fin_ai_lab.market_pulse.sources.nbp import NbpClient

PROMPTS_DIR = Path("src/fin_ai_lab/market_pulse/prompts")


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


async def test_ask_returns_the_llm_text_and_passes_tools() -> None:
    llm_client = FakeLlmClient({"ask": "Rentowność 10-letnich obligacji to 4.5%."})

    text = await ask(
        "Jaka jest rentowność 10-letnich obligacji USA?",
        llm_client,
        _prompt_registry(),
        "gemini-3.6-flash",
        FredClient("fake-key"),
        NbpClient(),
    )

    assert text == "Rentowność 10-letnich obligacji to 4.5%."
    assert len(llm_client.requests) == 1
    tool_names = {tool.__name__ for tool in llm_client.requests[0].tools}
    assert tool_names == {"get_fred_series_value", "get_nbp_fx_rate", "get_nbp_reference_rate"}
