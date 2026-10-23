# Praca z projektem: instalacja, konfiguracja, komendy

> Stan na 2026-10-23, commit `d0c43b4`. Wszystkie komendy i opcje sprawdzono w `src/fin_ai_lab/cli.py`, `pyproject.toml` i `.github/workflows/ci.yml`. Opis, co robi każdy moduł, jest w [PROJECT.md](PROJECT.md) i [reference/](reference/).

## 1. Wymagania

| Element | Wersja | Uwagi |
|---|---|---|
| Python | 3.12 (`.python-version`) | zarządzany przez uv. Nie używaj launchera `py` (wybiera 3.13t, dla którego brakuje kół binarnych) |
| uv | 0.11+ | menedżer projektu. **Wszystkie komendy uruchamiaj przez `uv run`** |
| Node.js | 22 | tylko dla interfejsu (`frontend/`) |
| Git | 2.30+ | |

Maszyna deweloperska ma procesor bez AVX2, 8 GB RAM i brak GPU. Konsekwencje (które paczki działają, trening tylko w chmurze) opisuje [ENVIRONMENT.md](ENVIRONMENT.md). Ścieżka repo na tej maszynie zawiera spację, więc cytuj ją w komendach.

## 2. Instalacja

```bash
uv sync                                                    # tylko rdzeń
uv sync --extra portfolio --extra rag --extra pulse --extra ml --extra groq --extra ui
cp .env.example .env                                       # i uzupełnij klucze
uv run pytest -q                                           # testy offline
uv run fin-ai-lab --help
```

Zestaw w drugiej linii to ten sam, który instaluje CI. Każdy projekt ma osobny extra, więc zwykłe `uv sync` instaluje tylko rdzeń, a testy brakujących extras są pomijane.

| Extra | Zawiera | Dla |
|---|---|---|
| `portfolio` | numpy, pandas, yfinance | P1, aplikacja webowa |
| `rag` | pypdf, numpy, bm25s | P2 |
| `pulse` | mcp, yfinance | P3 |
| `ml` | numpy, scikit-learn | P4 (baseline'y) |
| `groq` | groq | drugi dostawca LLM |
| `herbert` | torch, transformers | lokalna inferencja HerBERT (P4) |
| `quantized` | llama-cpp-python, peft, transformers | skwantyzowany Bielik (P4); `llama-cpp-python` buduje się ze źródła ok. 12 min |
| `ui` | fastapi, uvicorn, duckdb, python-multipart | aplikacja webowa |

Rdzeń: `google-genai`, `httpx`, `openpyxl`, `pydantic-settings`, `pyyaml`, `typer`. Grupa deweloperska: `pyright`, `pytest`, `pytest-asyncio`, `ruff`.

Interfejs:

```bash
cd frontend
npm install
```

## 3. Konfiguracja: plik `.env`

`.env` leży w katalogu, z którego uruchamiasz program, i jest poza gitem. **Klucze trzymaj tylko tam**: nie w kodzie, notatnikach ani czatach.

| Zmienna | Używana przez | Potrzebna do |
|---|---|---|
| `GEMINI_API_KEY` | `Settings` | wszystkiego z LLM i embeddingami (klucz z AI Studio, darmowy tier, bez billingu) |
| `GROQ_API_KEY` | `Settings` | etykietowania P4 (domyślnie Groq) i `--provider groq` |
| `SEC_USER_AGENT` | `Settings` | P2: SEC odrzuca żądania bez identyfikującego User-Agent, np. `fin-ai-lab ty@example.com` |
| `FRED_API_KEY` | `Settings` | P3, P5, backtest reżimu |
| `NTFY_TOPIC` | `Settings` | powiadomień push z P3 (temat działa jak hasło, wybierz nieodgadywalny) |
| `FIN_AI_LAB_MAX_RUN_COST_USD` | `Settings` | bezpiecznik kosztu, domyślnie `0` |

> **Zmienne w `.env.example`, których kod nie czyta:** `OPENFIGI_API_KEY`, `GUS_BDL_API_KEY`, `VOYAGE_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`. `Settings` ignoruje nieznane zmienne, więc ich ustawienie nic nie zmienia. `OpenFigiClient` ma parametr klucza, ale żadne wywołanie go nie przekazuje.

**Brak `GEMINI_API_KEY` nie przerywa programu**: komendy budują wtedy `FakeLlmClient` bez zaprogramowanych odpowiedzi. Rzeczy niewymagające modelu działają (np. import znanego formatu XTB), a pierwsze wywołanie LLM kończy się błędem `KeyError`.

### Zasady kosztów

Zero kosztów to zasada projektu. Klucz Gemini nie ma billingu, więc przekroczenie darmowego limitu kończy się błędem, nie obciążeniem. Szacunek kosztu powyżej `0` (np. po przypadkowym podpięciu billingu) zatrzymuje przebieg z pytaniem o zgodę. W trybie nieinteraktywnym przerywa go. Limity darmowego tieru `gemini-3.6-flash`: **5 żądań na minutę** (klient sam czeka 12 s między żądaniami) i **20 na dobę**. Szczegóły: [LLM-API.md](LLM-API.md).

## 4. Komendy CLI

`uv run fin-ai-lab <komenda>`. Daty w formacie `RRRR-MM-DD`. Domyślny model to `gemini-3.6-flash`.

| Komenda | Opis | Najważniejsze opcje |
|---|---|---|
| `version` | wersja pakietu | |
| `eval <suita>` | uruchamia suitę evali z katalogu `evals/<suita>/` | `--split dev\|test`, `--repeats N`, `--no-cache`, `--save-baseline`, `--yes`, `--max-cost USD`, `--provider gemini\|groq` |
| `portfolio import <plik.xlsx>` | wczytuje eksport XLSX i wypisuje pozycje | `--valuation-date` (wymagana), `--account-type` (`regular`, `ike`, `ikze`, `other`), `--market-currency` (PLN), `--broker` (tylko dla nieznanego formatu), `--yes`, `--broker-market`, `--no-identify` |
| `portfolio report <plik.xlsx>` | pełny raport opisowy | jak wyżej plus `--benchmark-ticker` (ticker Yahoo do liczenia bety), `--output` |
| `market-pulse brief` | brief rynkowy, alerty, zapis stanu | `--model`, `--output` |
| `market-pulse ask "<pytanie>"` | pytanie do agenta z narzędziami | `--model` |
| `filings-rag build-index` | buduje i zapisuje indeks raportów | `--model`, `--output` (domyślnie `data/index/filings_rag/index.npz`) |
| `news-classifier label` | zbiera nagłówki RSS i etykietuje nauczycielem | `--max-calls` (15), `--model` (`openai/gpt-oss-120b`), `--provider` (`groq`) |
| `news-classifier export-review` | próba do ręcznej recenzji na ślepo (CSV) | `--output`, `--sample-size` (500) |
| `news-classifier score-review` | kappa nauczyciela względem człowieka | `--reviewed` |
| `news-classifier compare-report` | raport porównawczy pięciu klasyfikatorów | `--output` |
| `investment-committee analyze <plik.xlsx>` | analiza portfela: pojedynczy agent lub komitet | `--valuation-date`, `--committee`, `--budget-usd` (1.00), `--max-iterations` (10), `--yes`, `--account-type`, `--market-currency`, `--broker`, `--model` |
| `investment-committee compare <plik.xlsx>` | A/B: pojedynczy agent kontra komitet | `--valuation-date`, `--budget-usd`, `--yes` i pozostałe jak wyżej |
| `web` | uruchamia backend aplikacji webowej | `--port` (`$PORT` albo 8010), `--db-path` |

Uwagi:

- Komendy `portfolio` i `investment-committee` czytają **XLSX** (np. XTB). Eksport Bossa (CSV) importuje się przez aplikację webową.
- `--yes` akceptuje nowo zaproponowaną konfigurację parsera i zgodę na przekroczenie budżetu bez pytania. Bez niego komenda pyta interaktywnie.
- Przebieg `eval` przerwany (Ctrl+C) zapisuje wyniki częściowe i kończy się kodem 1.

### Uruchamianie evali

```bash
uv run fin-ai-lab eval p1-injection
uv run fin-ai-lab eval p2-answer-accuracy --no-cache
uv run fin-ai-lab eval p4-classifier-few-shot --split test --provider groq
```

Wyniki: `evals/runs/<czas>-<kod>-<suita>/` (`results.jsonl`, `summary.json`, `report.md`, poza gitem). Baseline zapisuje się flagą `--save-baseline` do `evals/baselines/<suita>.json` (w repo). Metodologia: [EVALS.md](EVALS.md).

| Projekt | Suity |
|---|---|
| Fundament | `foundation-smoke` |
| P1 | `p1-import-accuracy`, `p1-injection`, `p1-report-faithfulness`, `p1-no-advice`, `p1-sector-accuracy` |
| P2 | `p2-retrieval-accuracy`, `p2-answer-accuracy`, `p2-web-answer-accuracy` |
| P3 | `p3-regime-backtest`, `p3-trajectory` |
| P4 | `p4-classifier-majority`, `-tfidf`, `-few-shot`, `-herbert`, `-quantized` |

Suity P3 (`p3-regime-backtest`) i P4 mają `cases.jsonl` budowane lokalnie (licencje danych), patrz [EVALS.md](EVALS.md). Dla P5 nie ma suit w `evals/`.

## 5. Aplikacja webowa

```bash
uv run fin-ai-lab web                  # backend na 127.0.0.1:8010
npm run dev --prefix frontend          # interfejs, zwykle http://localhost:5173
```

Plik `.claude/launch.json` definiuje oba serwery do podglądu w Claude Code (backend 8010, frontend 5173). Vite przekazuje `/api` i `/health` do backendu. Kontrola: `curl -s http://127.0.0.1:8010/health` zwraca `{"status":"ok"}`.

Karta "Zapytaj raport" wymaga zbudowanego indeksu (`filings-rag build-index`). Karta "Puls rynku" pokazuje brief z `data/briefs/`, który generuje zadanie z harmonogramu lub ręczne `market-pulse brief --output data/briefs/<data>.md`.

## 6. Zadania w Harmonogramie zadań Windows

Skrypty w `scripts/` rejestrują zadania **ręcznie, jednorazowo** z okna PowerShell (zmieniają stan systemu). Zadania działają w kontekście zalogowanego użytkownika, więc `uv` musi być w jego `PATH`.

| Rejestracja | Zadanie | Uruchamia | Wynik |
|---|---|---|---|
| `market_pulse_register_task.ps1` | `fin-ai-lab-market-pulse-brief`, codziennie 7:00 | `market_pulse_run_brief.ps1` → `market-pulse brief` | `data/briefs/<data>.md` i `.log` |
| `news_classifier_register_task.ps1` | `fin-ai-lab-news-classifier-label`, codziennie 6:30 | `news_classifier_run_labeling.ps1` → `news-classifier label --max-calls 300` | `data/news_classifier_runs/<data>.log` |
| `register_webapp_autostart_task.ps1` | `fin-ai-lab-portfolio-webapp-autostart`, przy logowaniu | `start_webapp.ps1` (backend i frontend w tle) | `data/private/webapp-logs/` |

Wyłączenie autostartu: `Unregister-ScheduledTask -TaskName 'fin-ai-lab-portfolio-webapp-autostart' -Confirm:$false`.

## 7. Gdzie są dane

Wszystko poniżej jest poza gitem (`.gitignore`), poza `evals/baselines/` i `evals/*/suite.yaml`.

| Ścieżka | Zawartość |
|---|---|
| `data/private/` | prawdziwe dane: eksporty brokerów, baza `portfolio_webapp.duckdb`, checkpointy HerBERT, adapter i model Bielika, pliki GPW |
| `data/cache/` | cache HTTP (per dostawca), cen Yahoo, embeddingów, kontekstu fragmentów, rerankera, evali |
| `data/corpus/news_classifier/` | korpus etykietowanych nagłówków |
| `data/review/` | CSV do ręcznej recenzji |
| `data/index/filings_rag/` | zapisany indeks raportów |
| `data/state/` | stan P3 między przebiegami |
| `data/briefs/` | briefy P3 |
| `data/memory/investment_committee/` | pamięć tez P5 (jeśli zapisywana) |
| `traces/` | ślady wywołań LLM (JSONL, jeden plik na dzień UTC) |
| `evals/runs/` | wyniki przebiegów evali |

Pliki cache można bezpiecznie usunąć, bo zostaną odtworzone przy następnym użyciu (kosztem czasu i limitu API).

## 8. Jakość kodu i CI

```bash
uv run ruff check .
uv run ruff format --check .      # albo `uv run ruff format .`
uv run pyright
uv run pytest -q
```

- `ruff`: reguły `E`, `F`, `I`, `UP`, długość linii 100, Python 3.12.
- `pyright`: tryb `basic`, tylko `src`.
- `pytest`: tryb asynchroniczny automatyczny, testy z `tests/`. Testy oznaczone `@pytest.mark.live` (prawdziwe API) są **domyślnie pomijane** (`-m 'not live'`). Aby je uruchomić: `uv run pytest -m live` (wymaga kluczy i zużywa limit).
- Interfejs: `npm run lint` i `npm run build` w `frontend/`.

CI (GitHub Actions, `.github/workflows/ci.yml`) działa przy pushu na `main` i na pull requestach:

| Zadanie | Co robi |
|---|---|
| Lint and format | `ruff check` i `ruff format --check` |
| Type check | `pyright` z extras jak w testach (bez `herbert` i `quantized`) |
| Tests | `pytest -q` na Linuksie i Windowsie, offline, bez kluczy |
| Frontend | `npm ci`, `npm run lint`, `npm run build` (Node 22) |

## 9. Rozwiązywanie problemów

| Objaw | Przyczyna i rozwiązanie |
|---|---|
| `ConfigError: GEMINI_API_KEY` (lub inny klucz) | brak zmiennej w `.env` albo uruchomienie z innego katalogu niż ten, w którym leży `.env` |
| `429` od Gemini | wyczerpany limit darmowego tieru (5/min lub 20/dobę). Klient nie ponawia 429, więc poczekaj do następnej doby. Użycie dziś pokaże pasek w interfejsie lub `GET /api/llm-usage` |
| `503` od Gemini | chwilowe przeciążenie. Klient ponawia raz, a każda próba liczy się do dziennego limitu. Spróbuj później |
| `Illegal instruction` lub awaria przy imporcie paczki | paczka binarna zbudowana pod AVX2. Zobacz [ENVIRONMENT.md](ENVIRONMENT.md) i `tests/test_environment.py` |
| Polskie znaki zniekształcone w pliku | PowerShell 5.1: używaj `-Encoding utf8` przy zapisie. CLI samo przestawia stdout na UTF-8 |
| `Unknown file format` przy imporcie | format nie ma zapisanej konfiguracji. Podaj `--broker` (CLI) albo użyj propose/approve (aplikacja) |
| `Report rejected: numbers not faithful` | kontrola wierności liczb odrzuciła raport modelu. Uruchom ponownie |
| Karta "Zapytaj raport": "Indeks raportów nie jest jeszcze zbudowany" | uruchom `filings-rag build-index` (wymaga `SEC_USER_AGENT`). Jeśli część spółek została pominięta, powtórz następnego dnia |
| `Budżet komitetu przekroczony` | limit kosztu lub iteracji `BudgetGuard`. Zwiększ `--budget-usd` lub `--max-iterations` albo potwierdź kontynuację |
| Zadanie z harmonogramu nic nie zapisuje | sprawdź plik `.log` obok wyniku. Zwykle `uv` nie jest w `PATH` konta, na którym działa zadanie |
| Backend nie wstaje na porcie 8010 | port zajęty. Użyj `--port` lub zmiennej `PORT` i zmień `vite.config.ts` (proxy) |
| Eval `p4-classifier-*` kończy się błędem o brakujących przypadkach | `cases.jsonl` nie jest w repo (licencja). Odtwórz je według [EVALS.md](EVALS.md) |
| Konwersja Bielika przerwana z różnicą tokenizacji | oczekiwane zabezpieczenie. Zobacz `src/fin_ai_lab/news_classifier/inference/README.md` |

## 10. Praca z Claude Code i RoleKit

Zasady pracy agenta, konwencje językowe i twarde zasady projektu są w [CLAUDE.md](../CLAUDE.md). Artefakty RoleKit (historia, specyfikacja, projekt techniczny) leżą w `docs/specs/<ticket>/`, a decyzje w `docs/adr/`. Plugin RoleKit jest poza repo i uruchamia się go flagą `--plugin-dir` (patrz CLAUDE.md).
