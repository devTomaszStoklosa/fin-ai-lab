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
        self.last_grammar: object | None = "not called yet"

    def create_chat_completion(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
        grammar: object | None = None,
    ):
        self.last_grammar = grammar
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


def test_classify_quantized_passes_no_grammar_for_an_injected_stub() -> None:
    # The real Label-schema grammar (issue #160) is only built on the real
    # load_llm() path -- an injected test stub never needed a real GGUF
    # file or the `quantized` extra before, and still doesn't.
    llm = _StubLlm(
        '{"sentiment": "positive", "event_type": "wyniki finansowe", "tickers": ["PKN"]}'
    )

    classify_quantized(_headline(), llm=llm)

    assert llm.last_grammar is None


def test_build_label_grammar_constructs_from_the_real_schema() -> None:
    pytest.importorskip("llama_cpp")
    from fin_ai_lab.news_classifier.inference.quantized import _build_label_grammar

    # No GGUF file needed -- grammar construction is a cheap, local
    # translation of Label's own JSON schema, not model inference.
    grammar = _build_label_grammar()

    assert grammar is not None
