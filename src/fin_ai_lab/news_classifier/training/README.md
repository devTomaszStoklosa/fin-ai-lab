# P4-S4/S5 — notebooki treningowe (Colab)

Nie część pakietu pip (`fin_ai_lab`) — same `.ipynb`, uruchamiane w Google Colab, nie lokalnie (maszyna deweloperska bez GPU/AVX2, patrz `docs/ENVIRONMENT.md`). Checkpointy nigdy nie trafiają do repo (gitignored `models/`, `checkpoints/`) — zostają na Google Drive właściciela.

## `herbert_finetune.ipynb` (P4-S4)

1. Wgraj `data/corpus/news_classifier/labeled.jsonl` (lokalny, gitignored) na swój Google Drive, np. `Mój dysk/fin-ai-lab/labeled.jsonl`.
2. Otwórz notebook w Colab (Google Drive → Otwórz w → Google Colaboratory, albo `colab.research.google.com` → Upload).
3. `Runtime` → `Change runtime type` → **T4 GPU**.
4. Uruchom komórki po kolei — druga komórka poprosi o zamontowanie Drive, ustaw `CORPUS_PATH` na ścieżkę z kroku 1.

Wynik: dwa niezależne checkpointy (`sentiment`, `event_type`) zapisane na Drive w `CHECKPOINT_DIR`, plus macro-F1 na test-split i kilka przykładowych predykcji.
