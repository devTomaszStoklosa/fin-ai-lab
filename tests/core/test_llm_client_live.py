import pytest

from fin_ai_lab.core.config import Settings
from fin_ai_lab.core.llm.client import GeminiLlmClient, LlmRequest

pytestmark = pytest.mark.live


async def test_complete_returns_result_from_real_api() -> None:
    settings = Settings()
    client = GeminiLlmClient(api_key=settings.require_gemini_api_key())
    request = LlmRequest(
        model="gemini-2.5-flash",
        messages=[{"role": "user", "text": "Reply with the single word: pong"}],
        max_output_tokens=50,
    )

    result = await client.complete(request)

    assert result.finish_reason == "STOP"
    assert result.cost_usd >= 0
    assert result.usage.input_tokens > 0
