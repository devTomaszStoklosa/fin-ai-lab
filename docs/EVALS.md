# Ewaluacja

Bez evali zmiana promptu, modelu czy pipeline'u to zgadywanie. Harness powstaje w `lab-foundation`, zanim ktokolwiek zacznie stroić prompty.

## Pojęcia

| Pojęcie | Znaczenie |
|---|---|
| Suita | zestaw przypadków + graderzy + konfiguracja celu (np. `p1-import-accuracy`) |
| Przypadek (case) | jedno wejście z oczekiwanym wynikiem lub rubryką |
| Grader | funkcja oceniająca wynik: deterministyczna albo LLM-as-judge |
| Przebieg (run) | wykonanie suity dla konkretnej wersji promptu, modelu i zbioru |
| Baseline | zapisane podsumowanie przebiegu, z którym porównujemy zmiany |
| Split | `dev` do iteracji, `test` odłożony — uruchamiany rzadko, to on jest wynikiem nagłówkowym |

## Pliki

```
evals/<suite>/suite.yaml         # konfiguracja
evals/<suite>/cases.jsonl        # przypadki
evals/baselines/<suite>.json     # podsumowanie baseline (w repo)
evals/runs/<timestamp>-<suite>/  # results.jsonl, summary.json, report.md (gitignored)
```

### Przypadek (`cases.jsonl`)

```json
{"id": "xtb-basic-001", "split": "dev", "input": {"file": "data/fixtures/p1/xtb_basic.xlsx"}, "expected": {"positions": [{"isin": "PLPKO0000016", "quantity": "120"}]}, "tags": ["happy-path"], "provenance": "synthetic"}
```

- `provenance`: `synthetic`, `human`, `teacher:<model>`, `rule` — skąd pochodzi etykieta.
- `tags` pozwalają raportować wyniki per kategoria (np. `injection`, `edge-case`, `unanswerable`).

### Suita (`suite.yaml`)

| Pole | Opis |
|---|---|
| `name`, `dataset_version` | zmiana `cases.jsonl` = podbicie wersji; baseline jest przypięty do wersji |
| `target` | ścieżka funkcji Pythona, np. `fin_ai_lab.portfolio_xray.service:import_file` |
| `model`, `effort`, `prompt_versions` | konfiguracja celu |
| `graders` | lista: typ, pole, parametry |
| `repeats` | liczba powtórzeń na przypadek (niedeterminizm modelu) |
| `concurrency` | limit równoległych wywołań |
| `max_cost_usd` | twardy limit przebiegu |

## Graderzy

| Typ | Do czego | Uwagi |
|---|---|---|
| `exact` | pola kategoryczne | normalizacja wielkości liter i białych znaków konfigurowalna |
| `numeric` | kwoty, ilości, metryki | tolerancja bezwzględna lub względna, porównanie na `Decimal` |
| `schema` | poprawność struktury | walidacja modelem Pydantic |
| `set_f1` | listy (tickery, pozycje) | precision, recall, F1 |
| `forbidden` | frazy zakazane (np. „kup", „sprzedaj", „powinieneś") | szybki filtr przed LLM-judge |
| `numbers_faithful` | każda liczba w tekście istnieje w danych źródłowych | parsuje formaty PL i EN, tolerancja zaokrągleń |
| `retrieval` | RAG | recall@k, MRR względem złotych fragmentów |
| `llm_judge` | jakość tekstu wg rubryki | wynik strukturalny `{score, pass, reason}` |
| `pairwise_judge` | A/B dwóch wariantów | kolejność losowana, sędzia nie wie, który wariant jest który |
| `classification_metrics` | pole kategoryczne (jak `exact`, ale nazwa gradera per pole — `grader:classification:<field>`) | zapisuje `expected`/`actual` w `details`, żeby raport porównawczy policzył prawdziwe macro-F1/confusion matrix z `results.jsonl` (P4-S7) — sam `avg_score` z runnera to trafność per przypadek, nie macro-F1 |

### Kalibracja LLM-as-judge

1. Oceń ręcznie co najmniej 30 przypadków.
2. Uruchom sędziego na tych samych przypadkach; policz zgodność (procent i kappa Cohena).
3. Poniżej ~0,6 kappa: popraw rubrykę albo prompt sędziego (nowa wersja), powtórz.
4. Prompt sędziego ma wersję jak każdy inny; zmiana sędziego unieważnia porównania z baseline.

## Runner

- Przed startem szacuje koszt (liczenie tokenów wejścia przez API `count_tokens` + założona długość wyjścia). Szacunek powyżej `max_cost_usd` lub `FIN_AI_LAB_MAX_RUN_COST_USD` = pytanie o zgodę.
- Cache wyników modelu kluczowany hashem (wejście, wersja promptu, model, parametry): zmiana samego gradera nie wydaje ponownie pieniędzy.
- `repeats` > 1 dla wyników niedeterministycznych: raport pokazuje średnią i rozrzut. Na Opus 5 i Sonnet 5 nie ustawia się `temperature` (API zwraca 400) — powtarzalność mierzymy powtórzeniami, nie „temperaturą zero".
- `stop_reason` = `max_tokens` lub `refusal` liczy się jako porażka z osobną kategorią.

## Raport przebiegu (`report.md`)

- Metryki per grader i per tag, delta względem baseline.
- Lista regresji per przypadek (przypadki, które przechodziły w baseline, a teraz nie).
- Koszt, tokeny, trafienia cache, latencja p50/p95.
- Pięć najgorszych przypadków z diffem oczekiwane / otrzymane.

## Zasady

1. Iteruj na `dev`. `test` uruchamiaj przy zamykaniu slice'a — inaczej prompt dopasuje się do testu.
2. W jednym przebiegu zmieniaj jedną rzecz: prompt, model albo zbiór.
3. Przykłady few-shot nigdy nie trafiają do zbioru ewaluacyjnego.
4. Dane szeregów czasowych dziel chronologicznie; usuwaj prawie identyczne przypadki między splitami.
5. Średnia nie zasłania regresji: raport zawsze listuje przypadki, które się pogorszyły.
6. Sędzia nie ocenia wyniku wygenerowanego tym samym promptem, który sam ocenia.
7. Brak tu lokalnego skilla do iteracyjnego strojenia promptu ani budowy suity (jak `claude-api hillclimb`/`build-eval` dla Anthropic) — strojenie i budowa suity są ręczne, według metodologii w tym dokumencie.

## Minimalne suity per projekt

| Projekt | Suita | Główna metryka |
|---|---|---|
| lab-foundation | `foundation-smoke` | harness działa end-to-end na atrapie |
| P1 | `p1-import-accuracy` | trafność per pole, odsetek poprawnych schematów |
| P1 | `p1-report-faithfulness` | odsetek raportów z wszystkimi liczbami zgodnymi z metrykami |
| P1 | `p1-no-advice` | odsetek raportów bez rekomendacji |
| P1 | `p1-injection` | odsetek przypadków, w których instrukcja z pliku została zignorowana |
| P2 | `p2-retrieval` | recall@5, MRR |
| P2 | `p2-answers` | poprawność, wierność kontekstowi, precyzja cytatów, trafne odmowy |
| P3 | `p3-trajectory` | właściwe narzędzia, liczba kroków, koszt przebiegu |
| P3 | `p3-regime-backtest` | zgodność z regułami, wynik na zanonimizowanej historii |
| P4 | `p4-classifier` | macro-F1 na ręcznie etykietowanym teście, latencja, koszt / 1000 newsów |
| P5 | `p5-committee-ab` | wygrane w porównaniu parami przy równym budżecie |
| P5 | `p5-claim-evidence` | odsetek twierdzeń z poprawnym źródłem |
