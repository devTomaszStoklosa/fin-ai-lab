from datetime import datetime

import pytest

import fin_ai_lab.news_classifier.inference.quantized as quantized
from fin_ai_lab.news_classifier.inference.quantized import classify_quantized
from fin_ai_lab.news_classifier.models import Headline, Label


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

    label = classify_quantized(_headline(), llm=llm, use_grammar=False)

    assert label.sentiment == "positive"
    assert label.event_type == "wyniki finansowe"
    assert label.tickers == ["PKN"]


def test_classify_quantized_raises_on_invalid_json() -> None:
    llm = _StubLlm("not json at all")

    with pytest.raises(ValueError, match="did not match Label schema"):
        classify_quantized(_headline(), llm=llm, use_grammar=False)


def test_classify_quantized_raises_on_out_of_enum_value() -> None:
    llm = _StubLlm(
        '{"sentiment": "very positive", "event_type": "wyniki finansowe", "tickers": []}'
    )

    with pytest.raises(ValueError, match="did not match Label schema"):
        classify_quantized(_headline(), llm=llm, use_grammar=False)


def test_classify_quantized_requires_model_path_or_llm() -> None:
    with pytest.raises(ValueError, match="needs either model_path or llm"):
        classify_quantized(_headline())


def test_classify_quantized_can_disable_grammar_for_an_injected_stub() -> None:
    llm = _StubLlm(
        '{"sentiment": "positive", "event_type": "wyniki finansowe", "tickers": ["PKN"]}'
    )

    classify_quantized(_headline(), llm=llm, use_grammar=False)

    assert llm.last_grammar is None


def test_classify_quantized_can_enable_grammar_for_an_injected_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grammar = object()
    monkeypatch.setattr(quantized, "_build_label_grammar", lambda: grammar)
    llm = _StubLlm(
        '{"sentiment": "positive", "event_type": "wyniki finansowe", "tickers": ["PKN"]}'
    )

    classify_quantized(_headline(), llm=llm, use_grammar=True)

    assert llm.last_grammar is grammar


@pytest.mark.asyncio
async def test_quantized_target_explicitly_enables_grammar(monkeypatch: pytest.MonkeyPatch) -> None:
    from fin_ai_lab.news_classifier import qa_target_quantized

    seen: dict[str, object] = {}

    def fake_classify(headline: Headline, *, llm: object, use_grammar: bool) -> Label:
        seen["headline"] = headline
        seen["llm"] = llm
        seen["use_grammar"] = use_grammar
        return Label(sentiment="neutral", event_type="inne", tickers=[])

    client = object()
    monkeypatch.setattr(qa_target_quantized, "_llm", lambda: client)
    monkeypatch.setattr(qa_target_quantized, "classify_quantized", fake_classify)

    result = await qa_target_quantized.quantized_target(_headline().model_dump(), None)

    assert result == {"sentiment": "neutral", "event_type": "inne", "tickers": []}
    assert seen["llm"] is client
    assert seen["use_grammar"] is True


def test_build_label_grammar_constructs_from_the_real_schema() -> None:
    pytest.importorskip("llama_cpp")
    from fin_ai_lab.news_classifier.inference.quantized import _build_label_grammar

    # No GGUF file needed -- grammar construction is a cheap, local
    # translation of Label's own JSON schema, not model inference.
    grammar = _build_label_grammar()

    assert grammar is not None
