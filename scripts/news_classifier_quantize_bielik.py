"""P4-S6: one-time local conversion of the P4-S5 Bielik LoRA adapter into
a quantized GGUF file for `inference/quantized.py`'s local CPU inference
(REQ-021 — latency/cost measured here, on this machine, not assumed from
Colab GPU).

Prerequisites (manual, one-time):
1. Copy the LoRA adapter from Drive (`herbert_finetune.ipynb`/
   `bielik_lora_finetune.ipynb`'s `CHECKPOINT_DIR`) into
   `data/private/bielik_lora_adapter/` (gitignored, same pattern as
   `data/private/herbert_checkpoints/`).
2. Clone llama.cpp (only its pure-Python `convert_hf_to_gguf.py` is
   needed here, no C++ build) into an isolated venv — its conversion
   requirements pin `transformers==4.57.6`/`torch==2.11.0`, both older
   than this project's own (`transformers>=5.0`), so they must not go
   into this repo's `.venv`:
       git clone https://github.com/ggml-org/llama.cpp tools/llama.cpp
       uv venv tools/convert-venv --python 3.12
       uv pip install --python tools/convert-venv -r \
           tools/llama.cpp/requirements/requirements-convert_hf_to_gguf.txt
       uv pip install --python tools/convert-venv "transformers==4.46.3"
   `tools/` is gitignored — local build tooling, not this repo's own code.
2b. Apply `scripts/patches/llama_cpp_hf_vocab_score.patch` on top of the
    fresh clone (issue #142 — upstream `LlamaHfVocab.get_token_score()`
    is an unfinished stub that always returns -1000.0 for every token,
    which produces empty/garbage completions for tokenizers without a
    `tokenizer.model`, like Bielik's):
       cd tools/llama.cpp && git apply ../../scripts/patches/llama_cpp_hf_vocab_score.patch
3. `uv sync --extra quantized` (llama-cpp-python, peft, transformers) in
   this repo's own `.venv`, for the merge and quantize steps below.
4. Accept `speakleash/Bielik-1.5B-v3.0-Instruct`'s access conditions and
   log in (`huggingface_hub.login()`), same as `bielik_lora_finetune.ipynb`.

Run: `uv run python scripts/news_classifier_quantize_bielik.py`.

Each step notes which adapter its output was built from
(`<output>.adapter-sha256`, `inference/build_record.py`) and rebuilds when
the adapter changes, so after retraining there is no need to delete the
old outputs by hand (issue #6).

Before converting, the merged tokenizer config gets the special tokens
llama.cpp's converter would otherwise miss; after every run, the script
checks that llama.cpp turns the classification prompt into exactly the
tokens transformers does (issue #7, `inference/conversion_tokenizer.py`).
"""

import json
import subprocess
from pathlib import Path

from fin_ai_lab.core.prompts.registry import PromptRegistry
from fin_ai_lab.news_classifier.inference.build_record import (
    adapter_fingerprint,
    discard_stale,
    is_built_from,
    record_built_from,
)
from fin_ai_lab.news_classifier.inference.conversion_tokenizer import (
    first_mismatch,
    with_additional_special_tokens,
)
from fin_ai_lab.news_classifier.inference.quantized import PROMPTS_DIR, TOKENIZER_KV_OVERRIDES
from fin_ai_lab.news_classifier.ticker_catalog import TICKER_CATALOG

MODEL_ID = "speakleash/Bielik-1.5B-v3.0-Instruct"
ADAPTER_DIR = Path("data/private/bielik_lora_adapter")
MERGED_DIR = Path("data/private/bielik_merged")
LLAMA_CPP_DIR = Path("tools/llama.cpp")
# The conversion script needs transformers==4.57.6/torch==2.11.0 (pinned
# by llama.cpp's own requirements file), incompatible with this repo's
# own transformers>=5.0 -- runs in the isolated venv from this script's
# docstring, never with this process's own interpreter.
CONVERT_PYTHON = Path("tools/convert-venv/Scripts/python.exe")
GGUF_F16_PATH = Path("data/private/bielik_quantized/model-f16.gguf")
GGUF_OUT_PATH = Path("data/private/bielik_quantized/model.gguf")

# ASSUMPTION: Q4_K_M is llama.cpp's own recommended default trade-off
# (size vs. quality) for a model this small — not tuned against this
# corpus, revisit if P4-S7's comparison report shows it's the bottleneck.
QUANT_TYPE = "Q4_K_M"

# Synthetic (headline, lead) pairs for the tokenizer check: Polish
# diacritics, digits and a ticker, run through the real classification
# prompt -- so every chat marker and the JSON instructions are covered too.
TOKENIZER_CHECK_HEADLINES = [
    ("Orlen podaje wyniki finansowe za III kwartał", "Zysk netto wzrósł o 12% r/r."),
    ("KGHM obniża prognozę wydobycia miedzi", ""),
    ("Zarząd PKO BP rekomenduje wypłatę dywidendy", "Łącznie 5,2 zł na akcję."),
]


def _is_current(output: Path, fingerprint: str, step: str) -> bool:
    """True when `output` was built from this adapter; otherwise clears
    whatever stale output is there, so the step rebuilds from scratch."""
    if is_built_from(output, fingerprint):
        print(f"{output} already built from this adapter, skipping {step}")
        return True
    if output.exists():
        print(f"{output} was built from a different or unknown adapter, redoing {step}")
    discard_stale(output)
    return False


def merge_adapter(fingerprint: str) -> None:
    if _is_current(MERGED_DIR, fingerprint, "merge"):
        return

    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    print(f"Loading base model {MODEL_ID}...")
    base_model = AutoModelForCausalLM.from_pretrained(MODEL_ID)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)

    print(f"Merging LoRA adapter from {ADAPTER_DIR}...")
    merged = PeftModel.from_pretrained(base_model, ADAPTER_DIR).merge_and_unload()

    MERGED_DIR.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(MERGED_DIR)
    tokenizer.save_pretrained(MERGED_DIR)
    record_built_from(MERGED_DIR, fingerprint)
    print(f"Saved merged model to {MERGED_DIR}")


def add_special_tokens_for_converter(merged_dir: Path) -> None:
    """Issue #7: the converter's transformers 4.x can't see the special
    tokens transformers 5 saved under `extra_special_tokens` (see
    `conversion_tokenizer.py`) -- list them where it looks. Done right
    before converting, not when merging, because merging is skipped while
    the adapter stays the same."""
    config_path = merged_dir / "tokenizer_config.json"
    tokenizer_config = json.loads(config_path.read_text(encoding="utf-8"))
    tokenizer_json = json.loads((merged_dir / "tokenizer.json").read_text(encoding="utf-8"))
    updated = with_additional_special_tokens(tokenizer_config, tokenizer_json)
    config_path.write_text(
        json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Listed for the converter: {updated['additional_special_tokens']}")


def convert_to_gguf(fingerprint: str) -> None:
    if _is_current(GGUF_F16_PATH, fingerprint, "conversion"):
        return

    convert_script = LLAMA_CPP_DIR / "convert_hf_to_gguf.py"
    if not convert_script.exists():
        raise FileNotFoundError(
            f"{convert_script} not found — clone llama.cpp first (see this script's docstring)"
        )
    if not CONVERT_PYTHON.exists():
        raise FileNotFoundError(
            f"{CONVERT_PYTHON} not found — create the isolated conversion venv first"
            " (see this script's docstring)"
        )

    add_special_tokens_for_converter(MERGED_DIR)
    GGUF_F16_PATH.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(CONVERT_PYTHON),
            str(convert_script),
            str(MERGED_DIR),
            "--outfile",
            str(GGUF_F16_PATH),
            "--outtype",
            "f16",
        ],
        check=True,
    )
    record_built_from(GGUF_F16_PATH, fingerprint)


def quantize(fingerprint: str) -> None:
    if _is_current(GGUF_OUT_PATH, fingerprint, "quantization"):
        return

    from llama_cpp import llama_cpp as lcpp

    params = lcpp.llama_model_quantize_default_params()
    params.ftype = getattr(lcpp, f"LLAMA_FTYPE_MOSTLY_{QUANT_TYPE}")

    return_code = lcpp.llama_model_quantize(
        str(GGUF_F16_PATH).encode(), str(GGUF_OUT_PATH).encode(), params
    )
    if return_code != 0:
        raise RuntimeError(f"llama_model_quantize failed with code {return_code}")
    record_built_from(GGUF_OUT_PATH, fingerprint)
    print(f"Quantized ({QUANT_TYPE}) model written to {GGUF_OUT_PATH}")


def check_tokenizer() -> None:
    """Issue #7: fail unless llama.cpp, loaded the way `classify_quantized`
    loads it, turns the classification prompt into exactly the tokens
    transformers does -- the tokens the model is fine-tuned on. Runs even
    when every step above was skipped, so an older GGUF is caught too."""
    from llama_cpp import Llama  # pyright: ignore[reportMissingImports]  # extra "quantized"
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(MERGED_DIR)
    llm = Llama(
        model_path=str(GGUF_OUT_PATH),
        vocab_only=True,
        verbose=False,
        kv_overrides=TOKENIZER_KV_OVERRIDES,
    )
    prompts = PromptRegistry()
    prompts.load_dir(PROMPTS_DIR)
    prompt = prompts.get("bielik_sft", 1)
    catalog_json = json.dumps(TICKER_CATALOG, ensure_ascii=False)

    for headline, lead in TOKENIZER_CHECK_HEADLINES:
        rendered = prompt.render(headline=headline, lead=lead, ticker_catalog_json=catalog_json)
        text = tokenizer.apply_chat_template(
            [{"role": "user", "content": rendered}], tokenize=False, add_generation_prompt=True
        )
        expected = tokenizer(text, add_special_tokens=False)["input_ids"]
        # What llama-cpp-python's create_chat_completion does with the
        # template it renders: special tokens parsed, no extra BOS.
        actual = llm.tokenize(text.encode("utf-8"), add_bos=False, special=True)
        position = first_mismatch(expected, actual)
        if position is not None:
            shown = slice(position, position + 8)
            llama_pieces = [
                llm.detokenize([token], special=True).decode("utf-8", "replace")
                for token in actual[shown]
            ]
            raise RuntimeError(
                f"llama.cpp tokenizes the prompt for '{headline}' differently from"
                f" transformers, starting at token {position}:\n"
                f"  transformers: {tokenizer.convert_ids_to_tokens(expected[shown])}\n"
                f"  llama.cpp:    {llama_pieces}\n"
                f"Delete {GGUF_F16_PATH.parent} and run this script again to rebuild"
                " the GGUF from the same adapter."
            )
    print(
        f"Tokenizer check passed: llama.cpp matches transformers on"
        f" {len(TOKENIZER_CHECK_HEADLINES)} classification prompts"
    )


def main() -> None:
    # Fails before any step touches its output when the adapter is missing.
    fingerprint = adapter_fingerprint(ADAPTER_DIR)
    merge_adapter(fingerprint)
    convert_to_gguf(fingerprint)
    quantize(fingerprint)
    check_tokenizer()


if __name__ == "__main__":
    main()
