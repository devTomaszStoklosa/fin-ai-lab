# P4-S6 — kwantyzacja i lokalna inferencja

`quantized.py` jest częścią pakietu pip (`fin_ai_lab`), w przeciwieństwie do notebooków w `training/` — ale wymaga pliku `.gguf`, którego repo nie zawiera (gitignored `*.gguf`, `data/private/`).

## Jednorazowa konwersja (`scripts/news_classifier_quantize_bielik.py`)

1. Skopiuj adapter LoRA z Drive (`CHECKPOINT_DIR` z `bielik_lora_finetune.ipynb`) do `data/private/bielik_lora_adapter/` — ten sam wzorzec co `data/private/herbert_checkpoints/`.
2. Sklonuj llama.cpp (tylko skrypt konwersji, bez budowania C++) do **osobnego** venv — jego wymagania przypinają `transformers==4.57.6`/`torch==2.11.0`, starsze niż w tym repo (`transformers>=5.0`), więc nie mogą trafić do `.venv` tego projektu:
   ```bash
   git clone https://github.com/ggml-org/llama.cpp tools/llama.cpp
   uv venv tools/convert-venv --python 3.12
   uv pip install --python tools/convert-venv -r tools/llama.cpp/requirements/requirements-convert_hf_to_gguf.txt
   ```
   `tools/` jest gitignored — to lokalne narzędzie budowy, nie kod tego repo.
3. `uv sync --extra quantized` (`llama-cpp-python`, `peft`, `transformers`).
4. Zaakceptuj warunki `speakleash/Bielik-1.5B-v3.0-Instruct` i zaloguj się (`huggingface_hub.login()`), jak w `bielik_lora_finetune.ipynb`.
5. `uv run python scripts/news_classifier_quantize_bielik.py` — scala adapter z bazowym modelem, konwertuje do GGUF (f16), kwantyzuje (Q4_K_M) do `data/private/bielik_quantized/model.gguf`.

## Uruchomienie ewaluacji

Po konwersji: `fin-ai-lab eval p4-classifier-quantized --split test`, potem `fin-ai-lab news-classifier compare-report` (P4-S7) obejmie już piąty model.

## Znane ograniczenie (2026-09-19): pusta odpowiedź modelu po konwersji

Pipeline (klon, merge, konwersja, kwantyzacja, inferencja lokalna) przechodzi end-to-end i realnie mierzy latencję na tym CPU (~197ms p95) — ale **sam skwantyzowany model generuje pustą odpowiedź** na każdy prompt, więc `p4-classifier-quantized`'s macro-F1 w raporcie P4-S7 wychodzi 0.000. Zdiagnozowane: to nie jest bug w tym repo ani w modelu z P4-S5 — scalony model (`data/private/bielik_merged/`) działa poprawnie przez `transformers` (`model.generate()` daje sensowny tekst). Błąd wchodzi w konwersji HF→GGUF: Bielik nie dystrybuuje `tokenizer.model` (tylko `tokenizer.json`), więc `convert_hf_to_gguf.py` używa zapasowej ścieżki `gguf.LlamaHfVocab` — znanej z niedopracowanego mapowania tokenów dla modeli bez natywnego sentencepiece. Dodatkowo `requirements-convert_hf_to_gguf.txt`'s `transformers==4.57.6` crashuje na tej ścieżce (`AttributeError: 'list' object has no attribute 'keys'`) — obejście: `uv pip install --python tools/convert-venv "transformers==4.46.3"` pozwala konwersji dokończyć, ale nie naprawia samego mapowania wokabularza.

Nie naprawione dalej — to wykracza poza cel repo (nauka pipeline'u kwantyzacji, nie łatanie llama.cpp). Śledzone w [issue #142](https://github.com/devTomaszStoklosa/fin-ai-lab/issues/142). Metodologia pomiaru latencji (REQ-021) jest sprawdzona i działa — to jakość tej jednej konwersji jest podejrzana, nie sposób mierzenia.
