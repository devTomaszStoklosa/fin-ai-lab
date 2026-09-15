# lab-foundation - Specification

Status: Ready for dev
Owner role: BA
Upstream: 01-story.md

## Glossary

| Term | Meaning |
|---|---|
| Suita | `evals/<suite>/suite.yaml` + `cases.jsonl`; jednostka uruchomienia evala |
| Przypadek | jedna linia `cases.jsonl` z wejściem i oczekiwaniem |
| Cel (target) | funkcja Pythona wykonywana dla każdego przypadku |
| Grader | funkcja oceniająca wynik celu dla przypadku |
| Przebieg | jedno wykonanie suity; katalog `evals/runs/<timestamp>-<suite>/` |
| Baseline | podsumowanie przebiegu zapisane w `evals/baselines/<suite>.json` |
| Span | jedno zdarzenie w trace (wywołanie LLM, narzędzia, krok) |
| Wersja promptu | liczba `N` w nazwie pliku `<id>.v<N>.md` |
| Wersja zbioru | `dataset_version` w `suite.yaml` |
| Test live | test wymagający sieci i klucza API, domyślnie pomijany |

## Actors and permissions

| Actor | Action | Allowed |
|---|---|---|
| Właściciel (CLI) | uruchamia testy i evale, zatwierdza koszt, zapisuje baseline | tak |
| Kod projektu | wywołuje `LlmClient` i `PromptRegistry` | tak |
| Kod projektu | wywołuje SDK `google-genai` z pominięciem `core.llm` | nie |
| Test bez znacznika `live` | wysyła żądania sieciowe | nie |

## Functional requirements (EARS)

Konfiguracja
- REQ-001 (AC-1): The system shall load settings from environment variables and an optional `.env` file in the repo root.
- REQ-002 (AC-3): If a command requires `GEMINI_API_KEY` and the variable is not set, then the system shall stop with a configuration error that names the missing variable.
- REQ-003: The system shall never write secret values to logs, traces or reports.

Klient LLM
- REQ-010 (AC-2): When a model call completes, the LLM client shall return content, stop reason, token usage (input, output, cache read, cache write), cost in USD, latency and trace id.
- REQ-011 (AC-2): When a model call completes or fails, the LLM client shall append one span to the trace file for the current UTC day.
- REQ-012: If the requested model has no entry in the pricing table, then the LLM client shall raise an error before sending the request.
- REQ-013: If the stop reason is `max_tokens` or `refusal`, then the LLM client shall mark the result as incomplete and expose the reason.
- REQ-014: Where a response schema is provided, the LLM client shall return a validated object, or raise a validation error with the raw response attached.
- REQ-015: The LLM client shall accumulate cost per run so the eval runner can report totals.

Prompty
- REQ-020: The prompt registry shall load prompts by id and version from versioned files.
- REQ-021 (AC-7): If a required variable is missing at render time, then the prompt registry shall raise an error that names the variable.
- REQ-022: If two prompt files declare the same id and version, then the prompt registry shall raise an error when loading.

Evale
- REQ-030 (AC-4): When `fin-ai-lab eval <suite>` runs, the runner shall execute the target for every case of the selected split (times `repeats`), apply the graders and write `results.jsonl`, `summary.json` and `report.md` to a new run directory.
- REQ-031 (AC-4): The report shall show metrics per grader and per tag, total cost, token totals and latency p50 and p95.
- REQ-032 (AC-5): Where a baseline exists for the same suite and dataset version, the report shall show metric deltas and list the cases that passed in the baseline and fail now.
- REQ-033 (AC-6): Before executing any case, the runner shall estimate the run cost; if the estimate exceeds the suite limit or `FIN_AI_LAB_MAX_RUN_COST_USD`, then the runner shall ask for confirmation, or abort when the session is not interactive.
- REQ-034: When a case with the same input, prompt versions, model and parameters was already executed, the runner shall reuse the cached output unless `--no-cache` is given.
- REQ-035: The runner shall provide the graders `exact`, `numeric`, `schema`, `set_f1`, `forbidden` and `llm_judge`.
- REQ-036: When `fin-ai-lab eval <suite> --save-baseline` completes without aborting, the runner shall write the run summary to `evals/baselines/<suite>.json`.
- REQ-037: The runner shall execute only cases of the selected split, `dev` by default.
- REQ-038: If the target raises an exception for a case, then the runner shall record that case as failed with an error category and continue with the remaining cases.
- REQ-039: When a run is interrupted, the runner shall keep the results written so far and mark the summary as incomplete.

Środowisko
- REQ-040 (AC-8): The test suite shall include an environment test that imports every native dependency of the project and performs one operation with it.
- REQ-041 (AC-1): The test suite shall run without network access or API keys; tests marked `live` shall be skipped unless explicitly selected.

## Business rules

Strażnik kosztów — domyślny limit `0` (zasada zero kosztów, klucz bez billingu, patrz LLM-API.md): w praktyce każdy szacunek > 0 traktowany jak przekroczenie, więc tabela poniżej działa jako fail-safe na anomalię, a nie jako codzienne hamowanie. Ochronę przed przerwanym w połowie przebiegiem daje throttling `core.http` dopasowany do RPM/RPD, nie ten strażnik.

| Szacunek ≤ limit | Sesja interaktywna | Wynik |
|---|---|---|
| tak | dowolna | przebieg startuje |
| nie lub nieznany | tak | pytanie; start tylko po jawnym „tak" albo z flagą `--yes` |
| nie lub nieznany | nie | przerwanie z komunikatem: szacunek i limit |

Porównanie z baseline

| Baseline istnieje | Zgodna `dataset_version` | Wynik |
|---|---|---|
| nie | – | raport bez delt, podpowiedź `--save-baseline` |
| tak | tak | delty i lista regresji |
| tak | nie | raport bez delt, ostrzeżenie o zmianie zbioru |

## Data and validation

Przypadek (`cases.jsonl`)

| Field | Type | Required | Range or format | Validation message |
|---|---|---|---|---|
| `id` | string | tak | unikalny w suicie, `a-z0-9-` | `Duplicate case id '<id>' in suite '<suite>'` |
| `split` | string | nie | `dev` / `test`, domyślnie `dev` | `Unknown split '<value>'` |
| `input` | object | tak | – | `Case '<id>' has no input` |
| `expected` | object | nie | wymagany przez graderzy inne niż `llm_judge` | `Grader '<g>' needs expected.<field> in case '<id>'` |
| `tags` | list[string] | nie | – | – |
| `provenance` | string | tak | `synthetic` / `human` / `rule` / `teacher:<model>` | `Invalid provenance '<value>'` |

Suita (`suite.yaml`)

| Field | Type | Required | Range or format | Validation message |
|---|---|---|---|---|
| `name` | string | tak | zgodny z nazwą katalogu | `Suite name mismatch` |
| `dataset_version` | int | tak | ≥ 1 | `dataset_version must be >= 1` |
| `target` | string | tak | `module.path:function` | `Target '<value>' not importable` |
| `model` | string | nie | ID z cennika | `Unknown model '<value>'` |
| `effort` | string | nie | `low` … `max` | `Invalid effort '<value>'` |
| `prompt_versions` | map[string, int] | nie | wersje istniejące w rejestrze | `Prompt '<id>' has no version <n>` |
| `graders` | list | tak | co najmniej jeden | `Suite has no graders` |
| `repeats` | int | nie | 1–10, domyślnie 1 | `repeats out of range` |
| `concurrency` | int | nie | 1–16, domyślnie 4 | `concurrency out of range` |
| `max_cost_usd` | decimal | nie | > 0 | `max_cost_usd must be positive` |

Pola spanu trace: [docs/ARCHITECTURE.md](../../ARCHITECTURE.md#trace-jsonl).

## Edge and error cases

- Pusty `cases.jsonl` lub brak przypadków w splicie → błąd `Suite has no cases for split '<split>'`.
- Niepoprawna linia JSONL → błąd z numerem linii.
- 429 lub 5xx po wyczerpaniu ponowień SDK → przypadek nieudany z kategorią `api_error`, przebieg trwa dalej.
- Przerwanie Ctrl+C → zapisane wyniki zostają, podsumowanie `incomplete: true`.
- Dwa przebiegi w tej samej sekundzie → nazwa katalogu zawiera sekundy i krótki losowy sufiks.
- Polskie znaki w promptach, przypadkach i raportach → UTF-8 wszędzie, także na Windows.
- Ścieżka repo ze spacją → żadnego sklejania ścieżek w poleceniach powłoki.
- Tokeny zapisu i odczytu cache mają inne stawki niż zwykłe wejście → koszt liczony osobno dla każdej kategorii.
- Znaczniki czasu → UTC, ISO 8601.
- Nieznany szacunek kosztu (cel bez estymacji i bez historii) → traktowany jak przekroczenie limitu.

## Non-functional requirements

- Performance: `uv run pytest -q` poniżej 30 s na maszynie deweloperskiej; narzut runnera poniżej 1 s na 100 przypadków (bez czasu modelu).
- Security and privacy: brak sekretów w trace'ach i raportach (test sprawdza, że wartość klucza nie pojawia się w plikach); `traces/` i `evals/runs/` poza gitem.
- Audit and logging: każde wywołanie LLM ma span; każde podsumowanie przebiegu zawiera commit git (jeśli jest), wersje promptów, model, effort i wersję zbioru.

## Traceability

| AC | REQ |
|---|---|
| AC-1 | REQ-001, REQ-041 |
| AC-2 | REQ-010, REQ-011 |
| AC-3 | REQ-002 |
| AC-4 | REQ-030, REQ-031 |
| AC-5 | REQ-032 |
| AC-6 | REQ-033 |
| AC-7 | REQ-021 |
| AC-8 | REQ-040 |

## Open questions

| # | Question | Owner |
|---|---|---|
| 1 | Czy domyślny limit 1 USD na przebieg jest właściwy? | Tomasz |
| 2 | Sędzia LLM: `gemini-2.5-pro` domyślnie, czy tańszy/szybszy model po kalibracji w P1-S5? | Tomasz |
