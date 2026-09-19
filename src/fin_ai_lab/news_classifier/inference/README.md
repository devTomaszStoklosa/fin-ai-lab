# P4-S6 — kwantyzacja i lokalna inferencja

`quantized.py` jest częścią pakietu pip (`fin_ai_lab`), w przeciwieństwie do notebooków w `training/` — ale wymaga pliku `.gguf`, którego repo nie zawiera (gitignored `*.gguf`, `data/private/`).

## Jednorazowa konwersja (`scripts/news_classifier_quantize_bielik.py`)

1. Skopiuj adapter LoRA z Drive (`CHECKPOINT_DIR` z `bielik_lora_finetune.ipynb`) do `data/private/bielik_lora_adapter/` — ten sam wzorzec co `data/private/herbert_checkpoints/`.
2. Sklonuj llama.cpp (tylko skrypt konwersji, bez budowania C++) i zainstaluj jego wymagania:
   ```bash
   git clone https://github.com/ggml-org/llama.cpp tools/llama.cpp
   uv run python -m pip install -r tools/llama.cpp/requirements/requirements-convert_hf_to_gguf.txt
   ```
   `tools/` jest gitignored — to lokalne narzędzie budowy, nie kod tego repo.
3. `uv sync --extra quantized` (`llama-cpp-python`, `peft`, `transformers`).
4. Zaakceptuj warunki `speakleash/Bielik-1.5B-v3.0-Instruct` i zaloguj się (`huggingface_hub.login()`), jak w `bielik_lora_finetune.ipynb`.
5. `uv run python scripts/news_classifier_quantize_bielik.py` — scala adapter z bazowym modelem, konwertuje do GGUF (f16), kwantyzuje (Q4_K_M) do `data/private/bielik_quantized/model.gguf`.

## Uruchomienie ewaluacji

Po konwersji: `fin-ai-lab eval p4-classifier-quantized --split test`, potem `fin-ai-lab news-classifier compare-report` (P4-S7) obejmie już piąty model.
