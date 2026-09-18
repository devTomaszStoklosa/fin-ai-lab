from datetime import datetime
from pathlib import Path

import pytest

from fin_ai_lab.core.errors import ResponseValidationError
from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.news_classifier.baselines.few_shot_llm import classify_few_shot
from fin_ai_lab.news_classifier.models import Headline, Label, LabeledHeadline

PROMPTS_DIR = Path("src/fin_ai_lab/news_classifier/prompts")


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


def _headline(text: str) -> Headline:
    return Headline(headline=text, source="bankier", published_at=datetime(2026, 9, 17, 12, 0, 0))


def _example() -> LabeledHeadline:
    return LabeledHeadline(
        headline=_headline("Orlen podaje wyniki"),
        label=Label(sentiment="positive", event_type="wyniki finansowe", tickers=["PKN"]),
        source_model="teacher",
    )


async def test_classify_few_shot_parses_a_valid_response() -> None:
    label_json = '{"sentiment": "negative", "event_type": "spór prawny", "tickers": []}'
    llm_client = FakeLlmClient({"few_shot": label_json})

    label = await classify_few_shot(
        _headline("Spółka pozwana przez klienta"),
        llm_client,
        _prompt_registry(),
        "gemini-3.6-flash",
        training=[_example()],
    )

    assert label.sentiment == "negative"
    assert label.event_type == "spór prawny"


async def test_classify_few_shot_raises_response_validation_error_on_schema_mismatch() -> None:
    llm_client = FakeLlmClient({"few_shot": '{"sentiment": "positive"}'})  # missing fields

    with pytest.raises(ResponseValidationError):
        await classify_few_shot(
            _headline("Nagłówek"),
            llm_client,
            _prompt_registry(),
            "gemini-3.6-flash",
            training=[_example()],
        )


async def test_classify_few_shot_rejects_empty_training_set() -> None:
    llm_client = FakeLlmClient({})

    with pytest.raises(ValueError):
        await classify_few_shot(
            _headline("Nagłówek"), llm_client, _prompt_registry(), "gemini-3.6-flash", training=[]
        )


async def test_classify_few_shot_sends_only_example_count_examples_to_the_prompt() -> None:
    label_json = '{"sentiment": "neutral", "event_type": "inne", "tickers": []}'
    llm_client = FakeLlmClient({"few_shot": label_json})
    training = [_example() for _ in range(10)]

    await classify_few_shot(
        _headline("Nagłówek"),
        llm_client,
        _prompt_registry(),
        "gemini-3.6-flash",
        training=training,
        example_count=2,
    )

    rendered = llm_client.requests[0].messages[0]["text"]
    assert rendered.count("Orlen podaje wyniki") == 2
