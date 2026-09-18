# Środowisko deweloperskie

Stan sprawdzony 2026-09-14 na maszynie właściciela. Przy zmianie sprzętu zaktualizuj tabelę i sekcję konsekwencji.

## Maszyna

| Element | Wartość | Znaczenie |
|---|---|---|
| System | Windows 10 Pro 22H2 (19045) | Git Bash + PowerShell 5.1 |
| CPU | Intel i5-2500K (Sandy Bridge, 4 rdzenie / 4 wątki) | **AVX tak, AVX2 nie** |
| RAM | 8 GB | brak miejsca na ciężkie usługi lokalne |
| GPU | brak NVIDIA (`nvidia-smi` nie istnieje) | brak lokalnego treningu i szybkiej inferencji |
| Dysk C: | ok. 228 GB wolnego | wystarczy na dane i cache |
| Python | 3.13.5 (python.org), 3.13t free-threaded, CPython 3.12.13 zarządzany przez uv | repo przypięte do 3.12 |
| uv | 0.11.21 | menedżer projektu i Pythona |
| git | 2.30.1 | stary, ale wystarczy (`git init -b main` działa) |
| Docker | 29.4.0 (Docker Desktop, WSL2 tylko `docker-desktop`) | dostępny, ale zjada RAM |
| Node.js | 22.16.0 | wymagany przez RoleKit |
| Claude Code | 2.1.270 | RoleKit wymaga ≥ 2.1.196 |
| Ollama, `ant` CLI | brak | — |
| Klucze API (`GEMINI_API_KEY`, `FRED_API_KEY`, `VOYAGE_API_KEY`, `OPENFIGI_API_KEY`) | żaden nieustawiony | patrz [HANDOFF.md](../HANDOFF.md) |

## Konsekwencje

### 1. Brak AVX2

Nowoczesne binarne paczki bywają kompilowane pod AVX2 i kończą się błędem „Illegal instruction" albo cichym crashem.

| Paczka | Stan | Postępowanie |
|---|---|---|
| `polars` | standardowy build wymaga nowszych instrukcji CPU | użyj `polars-lts-cpu` albo `pandas` + `duckdb` |
| `faiss-cpu` | ryzyko wymagania AVX2 | niepotrzebny: wyszukiwanie wektorowe w `numpy` wystarczy dla korpusów do ~100 tys. chunków |
| `llama.cpp`, Ollama | zależy od wariantu buildu | zweryfikuj przed P4-S6 |
| `torch` (CPU), `onnxruntime`, `lancedb`, `sentence-transformers` | niezweryfikowane | test importu i jednej operacji przed adopcją |

Zasada: każda nowa zależność natywna dostaje test importu w `tests/test_environment.py` (patrz `lab-foundation`), a wynik trafia do tabeli zgodności poniżej.

### 2. 8 GB RAM

- Bez lokalnego Langfuse v3 (wymaga Postgresa, ClickHouse, Redisa i S3). Tracing: pliki JSONL, Arize Phoenix lokalnie albo Langfuse Cloud — decyzja w P3.
- Docker Desktop wyłączaj, gdy nie jest potrzebny.
- Embeddingi lokalnie tylko małymi modelami i małymi porcjami; duże korpusy przez API (Voyage) albo z cache na dysku.

### 3. Brak GPU

- Fine-tuning (P4) wyłącznie w chmurze: Google Colab (T4 16 GB) albo Kaggle (T4 / P100, tygodniowy limit godzin GPU).
- Lokalna inferencja dostrojonych modeli: encoder (HerBERT) albo mały, skwantyzowany decoder; latencję mierzymy, nie zakładamy.

### 4. Wolny CPU

- Testy jednostkowe mają być szybkie; ciężkie operacje (embeddingi, pobieranie danych) za cache na dysku.
- Evale zrównoleglają I/O (wywołania API), nie obliczenia CPU.

## Python

- Repo przypięte do 3.12 (`uv python pin 3.12`): najszersze wsparcie paczek ML. uv ma już tę wersję.
- Nie używaj launchera `py` — domyślnie wybiera 3.13t (free-threaded), dla którego brakuje wielu kół binarnych.
- Wszystko uruchamiaj przez `uv run`.

## Ścieżki i powłoki

- Repo leży w `C:\Users\Tomasz\Desktop\AI Lab\fin-ai-lab` — ścieżka ma spację. Cytuj ją zawsze; jeśli jakieś narzędzie jej nie znosi, zanotuj to tutaj.
- Git Bash: duże heredoki kończą się błędem „unexpected EOF" — zapisz skrypt do pliku.
- PowerShell 5.1: brak `&&` i `||`; zapisy plików z `-Encoding utf8` (polskie znaki).

## Tabela zgodności paczek

Uzupełniana przy każdym teście importu.

| Paczka | Wersja | Import i operacja testowa | Data | Uwagi |
|---|---|---|---|---|
| `numpy` | 2.5.3 | import + `array.sum()` | 2026-09-16 | OK, bez problemów z AVX2 |
| `pandas` | 3.0.5 | import + `DataFrame.sum()` | 2026-09-16 | OK |
| `yfinance` | 1.7.0 | import + `Ticker('AAPL').history()` (żywe pobranie) | 2026-09-16 | OK, ekstra `portfolio` (P1-S4) |
| `pypdf` | 6.19.0 | import + parsowanie realnego 10-K SEC (extract_text, outline) | 2026-09-16 | OK, czysty Python (bez natywnych rozszerzeń) — ekstra `rag` (P2-S1) |
| `bm25s` | 0.3.11 | import + `BM25().index()` + `retrieve()` na małym korpusie | 2026-09-17 | OK, bez problemów z AVX2 — ekstra `rag` (P2-S3, hybrid search) |
| `scikit-learn` | 1.9.1 | import + `TfidfVectorizer` + `LogisticRegression.fit/predict` | 2026-09-18 | OK, bez problemów z AVX2 — ekstra `ml` (P4-S3, baseline TF-IDF+LR) |
