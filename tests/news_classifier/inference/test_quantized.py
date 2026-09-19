from datetime import datetime

import pytest

from fin_ai_lab.news_classifier.inference.quantized import classify_quantized
from fin_ai_lab.news_classifier.models import Headline


def _headline() -> Headline:
    return Headline(
        headline="Orlen podaje wyniki finansowe",
        lead="Spółka informuje o wzroście przychodów",
        source="bankier",
        published_at=datetime(2026, 9, 18, 12, 0, 0),
    )


class _StubLlm:
    def __init__(self, content: str) -> None:
        self._content = content

    def create_chat_completion(self, messages: list[dict], *, max_tokens: int, temperature: float):
        return {"choices": [{"message": {"content": self._content}}]}


def test_classify_quantized_parses_a_valid_json_response() -> None:
    llm = _StubLlm(
        '{"sentiment": "positive", "event_type": "wyniki finansowe", "tickers": ["PKN"]}'
    )

    label = classify_quantized(_headline(), llm=llm)

    assert label.sentiment == "positive"
    assert label.event_type == "wyniki finansowe"
    assert label.tickers == ["PKN"]


def test_classify_quantized_raises_on_invalid_json() -> None:
    llm = _StubLlm("not json at all")

    with pytest.raises(ValueError, match="did not match Label schema"):
        classify_quantized(_headline(), llm=llm)


def test_classify_quantized_raises_on_out_of_enum_value() -> None:
    llm = _StubLlm(
        '{"sentiment": "very positive", "event_type": "wyniki finansowe", "tickers": []}'
    )

    with pytest.raises(ValueError, match="did not match Label schema"):
        classify_quantized(_headline(), llm=llm)


def test_classify_quantized_requires_model_path_or_llm() -> None:
    with pytest.raises(ValueError, match="needs either model_path or llm"):
        classify_quantized(_headline())
