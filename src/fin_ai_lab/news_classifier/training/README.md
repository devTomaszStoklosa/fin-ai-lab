# P4-S4/S5 — notebooki treningowe (Colab)

Nie część pakietu pip (`fin_ai_lab`) — same `.ipynb`, uruchamiane w Google Colab, nie lokalnie (maszyna deweloperska bez GPU/AVX2, patrz `docs/ENVIRONMENT.md`). Checkpointy nigdy nie trafiają do repo (gitignored `models/`, `checkpoints/`) — zostają na Google Drive właściciela.

## `herbert_finetune.ipynb` (P4-S4)

1. Wgraj `data/corpus/news_classifier/labeled.jsonl` (lokalny, gitignored) na swój Google Drive, np. `Mój dysk/fin-ai-lab/labeled.jsonl`.
2. Otwórz notebook w Colab (Google Drive → Otwórz w → Google Colaboratory, albo `colab.research.google.com` → Upload).
3. `Runtime` → `Change runtime type` → **T4 GPU**.
4. Uruchom komórki po kolei — druga komórka poprosi o zamontowanie Drive, ustaw `CORPUS_PATH` na ścieżkę z kroku 1.

Wynik: dwa niezależne checkpointy (`sentiment`, `event_type`) zapisane na Drive w `CHECKPOINT_DIR`, plus macro-F1 na test-split i kilka przykładowych predykcji.

## `bielik_lora_finetune.ipynb` (P4-S5)

1. Wgraj ten sam `data/corpus/news_classifier/labeled.jsonl` na Drive (można użyć tej samej ścieżki co dla `herbert_finetune.ipynb`).
2. Otwórz notebook w Colab.
3. `Runtime` → `Change runtime type` → **T4 GPU**.
4. `speakleash/Bielik-1.5B-v3.0-Instruct` jest gated (znalezione na żywo: 401 `GatedRepoError` bez tego) — zaakceptuj warunki na [karcie modelu](https://huggingface.co/speakleash/Bielik-1.5B-v3.0-Instruct) i przygotuj token odczytu (`huggingface.co/settings/tokens`) na komórkę logowania (`huggingface_hub.login()`).
5. Uruchom komórki po kolei — ustaw `CORPUS_PATH` jak w kroku 1.

Wynik: adapter LoRA (nie cały model, tylko wagi adaptera) zapisany na Drive w `CHECKPOINT_DIR`, plus macro-F1 na test-split i liczba błędów schematu (REQ-012 — model generatywny może zwrócić niepoprawny JSON/enum, liczone jako błąd, nie zgadywane).

## Lokalna inferencja (P4-S7)

Raport porównawczy (`fin-ai-lab news-classifier compare-report`, REQ-021) mierzy latencję/koszt HerBERT na tej samej maszynie, na której faktycznie działa — nie przejmuje liczb z Colab GPU. Skopiuj z Drive `CHECKPOINT_DIR/sentiment` i `CHECKPOINT_DIR/event_type` (całe foldery, z `config.json`/`model.safetensors`) do lokalnego `data/private/herbert_checkpoints/` (gitignored), potem `uv sync --extra herbert` i `fin-ai-lab eval p4-classifier-herbert --split test`.
