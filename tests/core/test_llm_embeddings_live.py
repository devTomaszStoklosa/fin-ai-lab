import pytest

from fin_ai_lab.core.config import Settings
from fin_ai_lab.core.llm.embeddings import GeminiEmbeddingClient

pytestmark = pytest.mark.live


async def test_embed_returns_a_distinct_vector_per_text_from_the_real_api() -> None:
    settings = Settings()
    client = GeminiEmbeddingClient(api_key=settings.require_gemini_api_key())

    result = await client.embed(["apples", "oranges"], model="gemini-embedding-2")

    assert len(result.vectors) == 2
    assert result.vectors[0] != result.vectors[1]
    assert result.cost_usd >= 0
