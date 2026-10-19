import json

from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.news_classifier.models import Headline, Label, LabeledHeadline
from fin_ai_lab.news_classifier.ticker_catalog import TICKER_CATALOG

# ASSUMPTION: 5 examples is a starting point, not a tuned value — 03-design.md
# doesn't fix a count. Deterministic (first N of `training`, not random) so
# a re-run of the same eval is reproducible.
DEFAULT_EXAMPLE_COUNT = 5


async def classify_few_shot(
    headline: Headline,
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    *,
    training: list[LabeledHeadline],
    example_count: int = DEFAULT_EXAMPLE_COUNT,
) -> Label:
    """P4-S3's third baseline (03-design.md): in-context learning from a
    handful of already-labeled examples, no fine-tuning — one LLM call per
    headline, same response_schema=Label pattern as labeling/teacher.py."""
    if not training:
        raise ValueError("training must not be empty")

    prompt = prompt_registry.get("few_shot", 1)
    request = LlmRequest(
        model=model,
        messages=[
            {
                "role": "user",
                "text": prompt.render(
                    examples=_format_examples(training[:example_count]),
                    headline=headline.headline,
                    lead=headline.lead or "",
                    ticker_catalog_json=json.dumps(TICKER_CATALOG, ensure_ascii=False),
                ),
            }
        ],
        response_schema=Label,
        prompt_id="few_shot",
        prompt_version=1,
    )
    result = await llm_client.complete(request)

    label = result.parsed
    if not isinstance(label, Label):
        raise ValueError(f"few-shot response for '{headline.headline}' did not match Label schema")
    return label


def _format_examples(examples: list[LabeledHeadline]) -> str:
    return "\n".join(
        f"- Nagłówek: {item.headline.headline}\n"
        f"  Lead: {item.headline.lead or ''}\n"
        f"  Etykieta: sentiment={item.label.sentiment}, event_type={item.label.event_type}, "
        f"tickers={item.label.tickers}"
        for item in examples
    )
