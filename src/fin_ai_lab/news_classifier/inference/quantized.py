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
    GGUF file or the `quantized` extra installed. `grammar` is typed as
    `object` (not `llama_cpp.LlamaGrammar`) for the same reason: this
    module must stay importable without the extra."""

    def create_chat_completion(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
        grammar: object | None = None,
    ) -> dict: ...


def load_llm(model_path: Path) -> ChatCompletionClient:
    from llama_cpp import Llama

    # 512 was too small once #142's vocab-conversion fix made tokenization
    # correct again — the real (correctly tokenized) prompt, including the
    # ticker catalog, runs 640-670 tokens; 2048 leaves headroom to grow.
    return Llama(model_path=str(model_path), n_ctx=2048, verbose=False)


def _build_label_grammar() -> object:
    # Issue #160: on a longer narrative-paragraph prompt, the lightly
    # fine-tuned LoRA sometimes ignores the instruction entirely and
    # echoes/continues the input as free-form prose instead of the
    # expected JSON. Grammar-constrained decoding masks every token that
    # doesn't fit the schema at each sampling step, which makes that
    # specific failure mode structurally impossible -- prose text isn't
    # valid at any position in a strict Label-shaped JSON grammar. It
    # can't fix a wrong classification, only a malformed one; llama.cpp's
    # own numerical precision and the LoRA's training quality are both
    # untouched (both explicitly out of scope for this repo per #160).
    from llama_cpp import LlamaGrammar

    return LlamaGrammar.from_json_schema(json.dumps(Label.model_json_schema()))


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
    grammar = None
    if llm is None:
        if model_path is None:
            raise ValueError("classify_quantized needs either model_path or llm")
        llm = load_llm(model_path)
        grammar = _build_label_grammar()

    prompts = PromptRegistry()
    prompts.load_dir(PROMPTS_DIR)
    prompt = prompts.get("bielik_sft", 1)
    rendered = prompt.render(
        headline=headline.headline,
        lead=headline.lead or "",
        ticker_catalog_json=json.dumps(TICKER_CATALOG, ensure_ascii=False),
    )

    result = llm.create_chat_completion(
        messages=[{"role": "user", "content": rendered}],
        max_tokens=128,
        temperature=0.0,
        grammar=grammar,
    )
    completion = result["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(completion)
        return Label.model_validate(parsed)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(
            f"quantized model response for '{headline.headline}' did not match Label schema"
        ) from exc
