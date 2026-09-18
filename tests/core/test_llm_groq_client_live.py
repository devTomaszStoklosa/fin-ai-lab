import pytest

from fin_ai_lab.core.config import Settings
from fin_ai_lab.core.llm.client import LlmRequest
from fin_ai_lab.core.llm.groq_client import GroqLlmClient

pytestmark = pytest.mark.live


async def test_complete_returns_result_from_real_api() -> None:
    settings = Settings()
    client = GroqLlmClient(api_key=settings.require_groq_api_key())
    request = LlmRequest(
        model="openai/gpt-oss-20b",
        messages=[{"role": "user", "text": "Reply with the single word: pong"}],
        max_output_tokens=50,
    )

    result = await client.complete(request)

    assert result.finish_reason == "stop"
    assert not result.incomplete
    assert result.cost_usd >= 0
    assert result.usage.input_tokens > 0
    assert result.tool_calls == []


async def test_complete_executes_a_real_tool_call() -> None:
    settings = Settings()
    client = GroqLlmClient(api_key=settings.require_groq_api_key())

    async def get_wig20_level() -> str:
        """Get the current WIG20 index level."""
        return "WIG20 is at 2500 points."

    request = LlmRequest(
        model="openai/gpt-oss-20b",
        messages=[
            {
                "role": "user",
                "text": "What is the WIG20 index level right now? Use the tool.",
            }
        ],
        max_output_tokens=200,
        tools=[get_wig20_level],
    )

    result = await client.complete(request)

    assert result.tool_calls == ["get_wig20_level"]
    assert "2500" in result.text
