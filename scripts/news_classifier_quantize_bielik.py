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
"""

import subprocess
from pathlib import Path

from fin_ai_lab.news_classifier.inference.build_record import (
    adapter_fingerprint,
    discard_stale,
    is_built_from,
    record_built_from,
)

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


def main() -> None:
    # Fails before any step touches its output when the adapter is missing.
    fingerprint = adapter_fingerprint(ADAPTER_DIR)
    merge_adapter(fingerprint)
    convert_to_gguf(fingerprint)
    quantize(fingerprint)


if __name__ == "__main__":
    main()
