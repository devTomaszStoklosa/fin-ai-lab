import json

from fin_ai_lab.core.errors import ResponseValidationError
from fin_ai_lab.core.llm.client import LlmClient, LlmRequest
from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.news_classifier.models import Headline, Label, LabeledHeadline
from fin_ai_lab.news_classifier.ticker_catalog import TICKER_CATALOG


async def label_with_teacher(
    headlines: list[Headline],
    llm_client: LlmClient,
    prompt_registry: PromptRegistry,
    model: str,
    *,
    max_calls: int | None = None,
) -> tuple[list[LabeledHeadline], list[str]]:
    """One call per headline (02-spec.md REQ-010) — no Batch API, per the
    live-checked 03-design.md correction (Batch API needs billing). Labels
    at most `max_calls` headlines and leaves the rest untouched: the caller
    (labeling/progress.py + whatever drives this daily) decides which
    headlines to pass in, so a repeated run never re-pays for an already
    labeled headline."""
    to_label = headlines if max_calls is None else headlines[:max_calls]
    prompt = prompt_registry.get("teacher", 1)
    catalog_json = json.dumps(TICKER_CATALOG, ensure_ascii=False)

    labeled: list[LabeledHeadline] = []
    errors: list[str] = []
    for headline in to_label:
        rendered = prompt.render(
            headline=headline.headline,
            lead=headline.lead or "",
            ticker_catalog_json=catalog_json,
        )
        request = LlmRequest(
            model=model,
            messages=[{"role": "user", "text": rendered}],
            response_schema=Label,
            prompt_id="teacher",
            prompt_version=1,
        )
        try:
            result = await llm_client.complete(request)
        except ResponseValidationError as exc:
            # REQ-012: a malformed generative result is a recorded error,
            # never a partial or guessed label.
            errors.append(f"{headline.headline}: {exc}")
            continue

        label = result.parsed
        if not isinstance(label, Label):
            errors.append(f"{headline.headline}: teacher response did not match Label schema")
            continue

        labeled.append(LabeledHeadline(headline=headline, label=label, source_model="teacher"))

    return labeled, errors
