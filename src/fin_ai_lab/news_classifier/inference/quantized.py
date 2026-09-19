import json
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.news_classifier.models import Headline, Label
from fin_ai_lab.news_classifier.ticker_catalog import TICKER_CATALOG

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


class ChatCompletionClient(Protocol):
    """Just enough of `llama_cpp.Llama`'s interface for `classify_quantized`
    to depend on — an injection seam (SOLID D) so tests never need a real
    GGUF file or the `quantized` extra installed."""

    def create_chat_completion(
        self, messages: list[dict], *, max_tokens: int, temperature: float
    ) -> dict: ...


def load_llm(model_path: Path) -> ChatCompletionClient:
    from llama_cpp import Llama

    return Llama(model_path=str(model_path), n_ctx=512, verbose=False)


def classify_quantized(
    headline: Headline,
    model_path: Path | None = None,
    *,
    llm: ChatCompletionClient | None = None,
) -> Label:
    """P4-S6 (REQ-021): local CPU inference of the quantized, LoRA
    fine-tuned Bielik (`scripts/news_classifier_quantize_bielik.py`'s
    output). Reuses `bielik_sft.v1` — the same prompt as P4-S5's training
    and evaluation loop — because a quantized model still only ever sees
    the prompt text, same as every other generative model here.

    An invalid JSON/enum response is a labeling error (REQ-012), raised
    as `ValueError` — the exact contract `baselines/few_shot_llm.py`
    already uses for the same failure mode, kept consistent rather than
    inventing a second error-reporting shape for one more model.

    `llm` is an injected chat-completion client (SOLID D) — `load_llm`
    builds a real one from `model_path` when `llm` isn't given, but a
    test can pass a stub instead."""
    if llm is None:
        if model_path is None:
            raise ValueError("classify_quantized needs either model_path or llm")
        llm = load_llm(model_path)

    prompts = PromptRegistry()
    prompts.load_dir(PROMPTS_DIR)
    prompt = prompts.get("bielik_sft", 1)
    rendered = prompt.render(
        headline=headline.headline,
        lead=headline.lead or "",
        ticker_catalog_json=json.dumps(TICKER_CATALOG, ensure_ascii=False),
    )

    result = llm.create_chat_completion(
        messages=[{"role": "user", "content": rendered}], max_tokens=128, temperature=0.0
    )
    completion = result["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(completion)
        return Label.model_validate(parsed)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(
            f"quantized model response for '{headline.headline}' did not match Label schema"
        ) from exc
