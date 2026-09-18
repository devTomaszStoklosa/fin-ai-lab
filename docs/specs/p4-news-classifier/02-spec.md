# p4-news-classifier - Specification

Status: Ready for architect
Owner role: BA
Upstream: 01-story.md

## Glossary

| Term | Meaning |
|---|---|
| Nagłówek | jeden tytuł + lead (do 150 znaków) z RSS, jedna jednostka klasyfikacji |
| Sentyment | ocena nagłówka z perspektywy akcjonariuszy: `negative` / `neutral` / `positive` |
| Typ zdarzenia | kategoria z zamkniętej listy (patrz Business rules), jedna na nagłówek |
| Katalog spółek | lista spółek/tickerów, do których wolno przypisać nagłówek — nierozstrzygnięte źródło, patrz Open questions #4 |
| Teacher | duży model (LLM) etykietujący korpus treningowy/testowy |
| Uczeń (student) | mały model dostrojony na etykietach teachera — cel: tani, szybki, lokalny |
| Zbiór treningowy / testowy | rozłączne podzbiory korpusu; split chronologiczny (01-story.md risk) |
| Kappa Cohena | miara zgodności między etykietą teachera a etykietą człowieka (docs/EVALS.md) |
| Wyciek między zbiorami (leakage) | prawie identyczny nagłówek obecny i w treningu, i w teście — zawyża wynik |

## Actors and permissions

| Actor | Action | Allowed |
|---|---|---|
| Właściciel | przegląda etykiety, porównuje modele, wybiera model produkcyjny | tak |
| Model (teacher, LLM) | etykietuje nagłówek: sentyment, typ zdarzenia, tickery | tak — tylko etykieta, nigdy finalny wynik bez ścieżki weryfikacji (P4-S2) |
| Człowiek (recenzent) | weryfikuje próbkę etykiet teachera, liczy zgodność | tak |
| Model (uczeń, dostrojony) | klasyfikuje nagłówek produkcyjnie po wytrenowaniu | tak — tylko klasyfikacja, nigdy rekomendacja inwestycyjna |
| Katalog spółek | źródło dozwolonych tickerów do przypisania | tak — tylko odczyt |

## Functional requirements (EARS)

Korpus i etykiety
- REQ-001 (AC-1): The system shall classify each headline (title + lead, ≤150 characters, Polish) into exactly one sentiment (`negative`/`neutral`/`positive`, shareholder perspective), exactly one event type from the closed list (Business rules), and zero or more tickers from the company catalog.
- REQ-002 (AC-2): If a headline names a company outside the catalog, then the system shall return an empty ticker list for that headline instead of a guessed or fuzzy-matched ticker.
- REQ-003 (AC-3): If a headline is not market-related, then the system shall classify it as event type `other` with sentiment `neutral`.
- REQ-004: The system shall keep only the headline's title and lead (≤150 characters) in the corpus — never the full article body (01-story.md out of scope).
- REQ-005: The system shall split the corpus chronologically into train/dev/test, and shall remove near-duplicate headlines that would otherwise appear in more than one split (01-story.md risk — data leakage).

Etykiety teachera i weryfikacja (P4-S2)
- REQ-010: The system shall produce teacher labels for the training corpus using a structured output schema (sentiment, event type, tickers) — never free-text parsed heuristically.
- REQ-011: The system shall have a human manually re-label a sample of teacher-labeled headlines (count: Open questions #2) and shall report agreement (percent + Cohen's kappa) between teacher and human, before that teacher's labels are trusted for training (docs/EVALS.md calibration methodology, ≥0.6 kappa bar).
- REQ-012 (AC-6): If the teacher (or any generative model in this pipeline) returns output that fails schema validation, then the system shall record it as a labeling error with a category, never as a partial or guessed label.

Ewaluacja modeli (AC-4, AC-5)
- REQ-020 (AC-5): The system shall report macro-F1 (sentiment and event type separately), confusion matrix, latency (p50/p95), and cost per 1000 headlines for every compared model: majority-class baseline, TF-IDF + logistic regression, few-shot LLM, and every fine-tuned model.
- REQ-021 (AC-4): When a fine-tuned model runs on the local CPU (docs/ENVIRONMENT.md — no AVX2, no GPU), the system shall measure and report its own latency (p50/p95) and cost per 1000 headlines, not assume figures from the training environment (Colab GPU).
- REQ-022: The system shall never evaluate a model on the same headlines it was trained or few-shot-prompted with (docs/EVALS.md rule 3 — few-shot examples never enter the eval set).

Guardrails
- REQ-030: The system shall not use classifier output (sentiment, event type, tickers) to generate a personalized investment recommendation (buy/sell/hold/increase/decrease) — same rule as P1/P2/P3, ADR 0006. The classifier labels a headline; it does not advise.
- REQ-031: The system shall not train on or redistribute any corpus or checkpoint whose license forbids it (e.g. FinancialPhraseBank's CC BY-NC-SA is reference/prototyping only, per docs/DATA-SOURCES.md — never the actual training set for a model the owner might reuse commercially later).

## Business rules

Decyzja: lista typów zdarzeń (zatwierdzona przez właściciela, 01-story.md pytanie #3)

`wyniki finansowe`, `dywidenda`, `emisja akcji`, `skup akcji`, `przejęcie lub fuzja`, `zmiana w zarządzie`, `prognoza`, `decyzja lub kara regulatora`, `spór prawny`, `umowa lub kontrakt`, `rekomendacja lub rating`, `makro`, `inne`.

Zamknięta lista — model (teacher i uczeń) nigdy nie wymyśla nowej kategorii; wynik spoza tej listy to błąd walidacji schematu (REQ-012), nie nowa etykieta.

Decyzja: sentyment przy braku jednoznacznego sygnału

| Sytuacja | Sentyment |
|---|---|
| Nagłówek jednoznacznie pozytywny/negatywny dla akcjonariuszy | `positive` / `negative` |
| Nagłówek neutralny informacyjnie (np. zmiana terminu publikacji) | `neutral` |
| Nagłówek niezwiązany z rynkiem (AC-3) | `neutral`, typ zdarzenia `other` |

## Data and validation

Nagłówek (wejście)

| Field | Type | Required | Uwagi |
|---|---|---|---|
| `headline` | string | tak | tytuł, bez limitu |
| `lead` | string | nie | ≤150 znaków (01-story.md out of scope: nie pełna treść artykułu) |
| `source` | string | tak | np. `bankier`, `strefa-inwestorow` (te same kanały RSS co P3, `market_pulse/sources/news.py`) |
| `published_at` | datetime | tak | do splitu chronologicznego (REQ-005) |
| `language` | string | tak | `pl` (01-story.md out of scope: inne języki tylko pomocniczo) |

Etykieta (wyjście klasyfikacji)

| Field | Type | Required | Uwagi |
|---|---|---|---|
| `sentiment` | enum | tak | `negative` / `neutral` / `positive` |
| `event_type` | enum | tak | zamknięta lista powyżej |
| `tickers` | list[string] | tak | może być pusta (REQ-002); wartości tylko z katalogu spółek |
| `source_model` | string | tak | który model wyprodukował etykietę (teacher / baseline / nazwa dostrojonego modelu) — potrzebne, żeby porównanie w AC-5 było odtwarzalne |

## Edge and error cases

- Nagłówek o spółce spoza katalogu — pusta lista tickerów, nie zgadnięty/dopasowany fuzzy ticker (REQ-002, AC-2).
- Nagłówek niezwiązany z rynkiem (np. sport, polityka lokalna trafiająca do kanału RSS przez pomyłkę) — `other`/`neutral` (REQ-003, AC-3).
- Wynik modelu generatywnego niezgodny ze schematem (zły enum, brakujące pole) — błąd z kategorią, nie częściowa etykieta (REQ-012, AC-6).
- Prawie identyczne nagłówki (przedruk, drobna redakcja) w różnych splitach — usunięte przed treningiem (REQ-005, 01-story.md risk).
- Rzadkie typy zdarzeń (np. kara regulatora) z za mało przykładami do stabilnego macro-F1 — zgłoszone w raporcie porównawczym (AC-5), nie ukrywane uśrednieniem (docs/EVALS.md zasada 5).
- Licencja FinancialPhraseBank (CC BY-NC-SA, niekomercyjna) — tylko materiał pomocniczy/prototypowy, nigdy właściwy zbiór treningowy (REQ-031).

## Open questions

| # | Question | Owner | Due |
|---|---|---|---|
| 1 | Teacher: Gemini (sprawdzić warunki trenowania na wynikach API) czy etykiety ręczne + teacher open-weight? | Tomasz | przed P4-S2 |
| 2 | Ile nagłówków zweryfikujesz ręcznie? Propozycja: 300–500 | Tomasz | przed P4-S2 |
| 3 | ~~Zatwierdzić listę typów zdarzeń?~~ Zatwierdzona bez zmian (Business rules powyżej). | Tomasz | rozstrzygnięte |
| 4 | Źródło katalogu spółek/tickerów (REQ-002) — pełna lista GPW czy podzbiór już znany z P1/P3? | Architect | przed P4-S1 |
