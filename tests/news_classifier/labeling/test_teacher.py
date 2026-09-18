from datetime import datetime
from pathlib import Path

from fin_ai_lab.core.llm.fake import FakeLlmClient
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.news_classifier.labeling.teacher import label_with_teacher
from fin_ai_lab.news_classifier.models import Headline

PROMPTS_DIR = Path("src/fin_ai_lab/news_classifier/prompts")


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.load_dir(PROMPTS_DIR)
    return registry


def _headline(text: str) -> Headline:
    return Headline(
        headline=text, source="bankier", published_at=datetime(2026, 9, 17, 12, 0, 0)
    )


async def test_label_with_teacher_parses_a_valid_response() -> None:
    label_json = '{"sentiment": "positive", "event_type": "wyniki finansowe", "tickers": ["PKN"]}'
    llm_client = FakeLlmClient({"teacher": label_json})

    labeled, errors = await label_with_teacher(
        [_headline("Orlen podaje wyniki")], llm_client, _prompt_registry(), "gemini-3.6-flash"
    )

    assert errors == []
    assert len(labeled) == 1
    assert labeled[0].label.sentiment == "positive"
    assert labeled[0].label.tickers == ["PKN"]
    assert labeled[0].source_model == "teacher"


async def test_label_with_teacher_records_a_malformed_response_as_an_error() -> None:
    llm_client = FakeLlmClient({"teacher": '{"sentiment": "positive"}'})  # missing required fields

    labeled, errors = await label_with_teacher(
        [_headline("Nagłówek")], llm_client, _prompt_registry(), "gemini-3.6-flash"
    )

    assert labeled == []
    assert len(errors) == 1


async def test_label_with_teacher_stops_at_max_calls() -> None:
    llm_client = FakeLlmClient(
        {"teacher": '{"sentiment": "neutral", "event_type": "inne", "tickers": []}'}
    )
    headlines = [_headline(f"Nagłówek {i}") for i in range(5)]

    labeled, _ = await label_with_teacher(
        headlines, llm_client, _prompt_registry(), "gemini-3.6-flash", max_calls=2
    )

    assert len(labeled) == 2
    assert len(llm_client.requests) == 2
