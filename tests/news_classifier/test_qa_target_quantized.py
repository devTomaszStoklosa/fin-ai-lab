from datetime import datetime

import pytest

from fin_ai_lab.news_classifier import qa_target_quantized


class _StubLlm:
    def __init__(self) -> None:
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
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"sentiment": "neutral", "event_type": "inne", "tickers": []}'
                    }
                }
            ]
        }


async def test_quantized_target_decodes_with_the_label_grammar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Issue #33: the eval target injects its own cached llm and used to
    # lose the grammar the docs describe as the classifier's safety net.
    llm = _StubLlm()
    grammar = object()
    monkeypatch.setattr(qa_target_quantized, "_llm", lambda: llm)
    monkeypatch.setattr(qa_target_quantized, "_grammar", lambda: grammar)
    case_input = {
        "headline": "Orlen podaje wyniki finansowe",
        "lead": None,
        "source": "bankier",
        "published_at": datetime(2026, 9, 18, 12, 0, 0).isoformat(),
    }

    output = await qa_target_quantized.quantized_target(case_input, None)  # type: ignore[arg-type]

    assert llm.last_grammar is grammar
    assert output["sentiment"] == "neutral"
