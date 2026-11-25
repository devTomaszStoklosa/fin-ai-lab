import json
from pathlib import Path
from typing import Protocol, cast

from pydantic import ValidationError

from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.news_classifier.models import Headline, Label
from fin_ai_lab.news_classifier.ticker_catalog import TICKER_CATALOG

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"

# Issue #7: llama.cpp puts a space after every special token, as
# transformers 4.x does; transformers 5, which the model is fine-tuned
# with, doesn't. The GGUF can't carry this itself (see
# conversion_tokenizer.py), so it's set at load time instead.
TOKENIZER_KV_OVERRIDES: dict[str, bool | int | float | str] = {
    "tokenizer.ggml.add_space_prefix": False
}


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
    from llama_cpp import Llama  # pyright: ignore[reportMissingImports]  # extra "quantized"

    # 512 was too small once #142's vocab-conversion fix made tokenization
    # correct again — the real (correctly tokenized) prompt, including the
    # ticker catalog, runs 640-670 tokens; 2048 leaves headroom to grow.
    llm = Llama(
        model_path=str(model_path),
        n_ctx=2048,
        verbose=False,
        kv_overrides=TOKENIZER_KV_OVERRIDES,
    )
    # Issue #34: Llama.create_chat_completion is wider than this Protocol —
    # typed message dicts, LlamaGrammar, and a stream iterator in its return
    # type — and the Protocol can't name llama_cpp's types without making
    # this module need the extra just to import. classify_quantized never
    # streams, so the call returns a plain response dict, which is all the
    # Protocol promises; the cast states that at this one boundary.
    return cast(ChatCompletionClient, llm)


def build_label_grammar() -> object:
    # Issue #160: the model ignored the instruction and echoed/continued
    # the input as free-form prose instead of the expected JSON. Root
    # cause was in training, not here: P4-S5's max_length=512 cut every
    # training example before its JSON answer (fixed in
    # bielik_lora_finetune.ipynb, needs a retrain). Grammar-constrained
    # decoding stays as a safety net: it masks every token that doesn't
    # fit the schema at each sampling step, so prose text can never come
    # out. It can't fix a wrong classification, only a malformed one.
    from llama_cpp import LlamaGrammar  # pyright: ignore[reportMissingImports]

    return LlamaGrammar.from_json_schema(json.dumps(Label.model_json_schema()))


def classify_quantized(
    headline: Headline,
    model_path: Path | None = None,
    *,
    llm: ChatCompletionClient | None = None,
    grammar: object | None = None,
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
    test can pass a stub instead.

    `grammar` is the JSON-schema grammar from `build_label_grammar()`.
    Issue #33: whether it's used is the caller's decision, not a side
    effect of where `llm` came from — the eval target injects its own
    cached `llm` and must still get the grammar-constrained decoding the
    docs describe, so it passes the grammar explicitly. The `model_path`
    path builds one itself when none is given; a test stub passes none."""
    if llm is None:
        if model_path is None:
            raise ValueError("classify_quantized needs either model_path or llm")
        llm = load_llm(model_path)
        if grammar is None:
            grammar = build_label_grammar()

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
