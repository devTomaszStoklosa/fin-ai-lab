# P4-S6 — kwantyzacja i lokalna inferencja

`quantized.py` jest częścią pakietu pip (`fin_ai_lab`), w przeciwieństwie do notebooków w `training/` — ale wymaga pliku `.gguf`, którego repo nie zawiera (gitignored `*.gguf`, `data/private/`).

## Jednorazowa konwersja (`scripts/news_classifier_quantize_bielik.py`)

1. Skopiuj adapter LoRA z Drive (`CHECKPOINT_DIR` z `bielik_lora_finetune.ipynb`) do `data/private/bielik_lora_adapter/` — ten sam wzorzec co `data/private/herbert_checkpoints/`.
2. Sklonuj llama.cpp (tylko skrypt konwersji, bez budowania C++) do **osobnego** venv — jego wymagania przypinają `transformers==4.57.6`/`torch==2.11.0`, starsze niż w tym repo (`transformers>=5.0`), więc nie mogą trafić do `.venv` tego projektu:
   ```bash
   git clone https://github.com/ggml-org/llama.cpp tools/llama.cpp
   uv venv tools/convert-venv --python 3.12
   uv pip install --python tools/convert-venv -r tools/llama.cpp/requirements/requirements-convert_hf_to_gguf.txt
   uv pip install --python tools/convert-venv "transformers==4.46.3"
   ```
   `tools/` jest gitignored — to lokalne narzędzie budowy, nie kod tego repo.
2b. Nałóż `scripts/patches/llama_cpp_hf_vocab_score.patch` na świeży klon (issue #142 — naprawia pustą odpowiedź modelu, patrz sekcja "Znane ograniczenia" poniżej):
   ```bash
   cd tools/llama.cpp && git apply ../../scripts/patches/llama_cpp_hf_vocab_score.patch
   ```
3. `uv sync --extra quantized` (`llama-cpp-python`, `peft`, `transformers`).
4. Zaakceptuj warunki `speakleash/Bielik-1.5B-v3.0-Instruct` i zaloguj się (`huggingface_hub.login()`), jak w `bielik_lora_finetune.ipynb`.
5. `uv run python scripts/news_classifier_quantize_bielik.py` — scala adapter z bazowym modelem, konwertuje do GGUF (f16), kwantyzuje (Q4_K_M) do `data/private/bielik_quantized/model.gguf`.

## Uruchomienie ewaluacji

Po konwersji: `fin-ai-lab eval p4-classifier-quantized --split test`, potem `fin-ai-lab news-classifier compare-report` (P4-S7) obejmie już piąty model.

## Znane ograniczenia

### Naprawione (2026-09-20): pusta odpowiedź modelu po konwersji — [issue #142](https://github.com/devTomaszStoklosa/fin-ai-lab/issues/142)

Główna przyczyna znaleziona w samym llama.cpp: `gguf-py/gguf/vocab.py`'s `LlamaHfVocab.get_token_score()` to niedokończony stub, który dla **każdego** tokenu zawsze zwraca `-1000.0` (`# Placeholder for actual logic ... This needs to be implemented`). Bez realnej różnicy w wynikach llama.cpp's tokenizer w stylu SPM (Viterbi) przy inferencji nie ma żadnego sygnału, żeby preferować prawdziwe scalenia BPE nad rozbiciem na bajty — tokenizuje tekst zupełnie inaczej niż podczas treningu modelu, co dawało puste/śmieciowe odpowiedzi.

Naprawa: `scripts/patches/llama_cpp_hf_vocab_score.patch` — liczy realny wynik per token z rankingu scaleń BPE (`tokenizer.json`'s `model.merges`), zamiast stałej `-1000.0`. Nałożyć na świeży klon `tools/llama.cpp` przed konwersją (krok 2b powyżej). Zweryfikowane bezpośrednią inferencją po ponownej konwersji: model odpowiada sensownym, poprawnym polskim tekstem (`f16` i `Q4_K_M`), zarówno przez `create_chat_completion` jak i surowe ChatML.

To lokalna łatka w gitignored `tools/` (nie nasz kod, nie upstreamowany do llama.cpp w tym repo).

### Nowe (2026-09-20/21): niespójna degeneracja odpowiedzi — nie długość, nie kwantyzacja, nie szablon

Po naprawie #142 krótkie samodzielne pytania/instrukcje (np. "Powiedz jedno zdanie o pogodzie", nawet krótki pojedynczy nagłówek + trywialna instrukcja) dają poprawną odpowiedź przez llama.cpp. Ale **pełny prompt klasyfikacyjny** (`bielik_sft.v1`, ~600-670 tokenów, `<data>` tagi + jawny schemat JSON) degeneruje się: model parafrazuje/echuje fragmenty własnych instrukcji, nigdy nie przechodząc do odpowiedzi (`finish_reason: length`). Ten sam prompt przez `transformers` na scalonym modelu daje poprawny JSON.

Dalsze zawężenie (2026-09-21) wykluczyło proste wyjaśnienia: nie kwantyzacja (identyczne dla f16), nie szablon czatu (identyczne dla ręcznego ChatML), nie rozmiar batcha prefill (`n_batch` = `n_ctx` bez zmiany), **nie sama długość promptu** — dłuższy narracyjny akapit + trywialna instrukcja degeneruje się już od ~43 tokenów, a krótki nagłówek + instrukcja działa poprawnie. To niespójne, zależne od treści zjawisko, nie jeden dyskretny bug.

Robocza hipoteza: krucha, nisko-marżowa granica decyzyjna w bardzo lekko dotrenowanym LoRA (92 nagłówki, P4-S5) między "kontynuuj tekst" (silny prior bazowego modelu) a "wykonaj instrukcję" (słaby sygnał z małego fine-tune'u) — różnice numeryczne między `llama.cpp` (CPU bez AVX2, fallback kernels) a `transformers` wystarczają, żeby przechylić tę granicę, zależnie od treści promptu. Dalsze pogłębianie wymagałoby debugowania precyzji numerycznej w C++ llama.cpp albo solidniejszego dotrenowania LoRA na większym korpusie — nieproporcjonalne do celu tego repo. `p4-classifier-quantized`'s macro-F1 w P4-S7 wciąż wychodzi 0. Śledzone w [issue #160](https://github.com/devTomaszStoklosa/fin-ai-lab/issues/160), zostawione otwarte z tą diagnozą — nie naprawiane dalej.
