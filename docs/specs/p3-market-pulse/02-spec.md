# p3-market-pulse - Specification

Status: Ready for architect
Owner role: BA
Upstream: 01-story.md

## Glossary

| Term | Meaning |
|---|---|
| Wskaźnik | jedna obserwacja liczbowa z zewnętrznego źródła (np. `DGS10`, EUR/PLN) na dany dzień |
| Reżim rynku | klasyfikacja stanu rynku: risk-on / neutral / risk-off |
| Brief | dzienne podsumowanie: wskaźniki, reżim z uzasadnieniem, zmiany od poprzedniego przebiegu |
| Alert | osobna, krótka wiadomość wysyłana tylko gdy wskaźnik przekroczy skonfigurowany próg zmiany |
| Przebieg | jedno uruchomienie agenta/workflow generujące brief (i ewentualnie alert) |
| Źródło niedostępne | wywołanie API źródła danych zawiodło albo nie zwróciło wartości dla żądanego dnia |

## Actors and permissions

| Actor | Action | Allowed |
|---|---|---|
| Właściciel | odczytuje brief, konfiguruje wskaźniki i progi alertów | tak |
| Model (LLM) | pisze uzasadnienie reżimu i podsumowanie zmian na podstawie policzonych wartości | tak — tylko z podanych wartości, bez liczb z pamięci |
| Model (LLM) | klasyfikuje reżim rynku (risk-on/neutral/risk-off) | nie — klasyfikacja to deterministyczna reguła w kodzie (CLAUDE.md zasada 2); model tylko opisuje już podjętą decyzję |
| Model (LLM) | rekomenduje kupno/sprzedaż/zmianę pozycji | nie — reguła repo (CLAUDE.md zasada 5, ADR 0006), tak jak w P1/P2 |
| Narzędzia danych (FRED/NBP/GDELT/yfinance) | zwracają wartości wskaźników i newsy | tak — tylko odczyt, żadnego zapisu u brokera (AC z `01-story.md`: „Out of scope") |
| Serwer MCP (P3-S3) | udostępnia te same narzędzia danych do użycia interaktywnego | tak — tylko odczyt |

## Functional requirements (EARS)

Wskaźniki i dane
- REQ-001 (AC-1): The system shall report indicator values for a configured allowlist of series, covering US macro/rates (FRED: public-domain series `DGS10`, `DGS2`, `T10Y2Y`, `DFF`, `CPIAUCSL`, `UNRATE`; third-party-licensed `VIXCLS` for learning use only, not redistributed — `docs/DATA-SOURCES.md`) and PL FX rates (NBP: EUR/PLN, USD/PLN).
- REQ-002 (AC-2): If a configured data source fails or returns no value for the requested day, then the system shall still build the brief from the remaining sources and shall explicitly list which source(s) were missing.
- REQ-003: The system shall never call the GDELT DOC 2.0 API from an automated/scheduled run (rate limit 1 req/5s, IP ban risk per `01-story.md` risks) — ad hoc/interactive use only.
- REQ-004: The system shall never rely on `yfinance` from an automated/scheduled run (unofficial, `docs/DATA-SOURCES.md`: "tylko lokalnie", "nie" w automatach) — interactive/local use only, if used at all.

Ocena reżimu i brief
- REQ-010 (AC-1): When a run completes, the system shall classify the overall market regime as risk-on, neutral, or risk-off using a deterministic, code-computed rule over the day's indicator values (CLAUDE.md rule 2: code computes, model explains) — never a label chosen by the model itself.
- REQ-011 (AC-1): The brief shall state which indicator values and thresholds drove the regime classification, so the rationale is traceable to the rule, not just asserted.
- REQ-012 (AC-1): The brief shall list each configured indicator's change since the previous run (day-over-day delta), not only its current value.
- REQ-013 (AC-2): The brief shall be generated even when one or more sources are missing (see REQ-002); the regime rule shall degrade to the indicators actually available and note the reduction in confidence/coverage.

Alerty
- REQ-020 (AC-3): When a configured indicator's day-over-day change crosses its configured threshold, the system shall send an alert describing the indicator, its previous and new value, and the threshold crossed.
- REQ-021 (AC-4): When no configured indicator crosses its threshold, the system shall not send an alert.
- REQ-022: Alert thresholds are per-indicator configuration values, not hardcoded assumptions baked into the rule (mirrors P2's `refusal_threshold` pattern: starting values are an ASSUMPTION, calibrated later against real data — P3-S8 backtest).

Observability i koszt
- REQ-030 (AC-5): Every run shall produce a trace recording every tool call, its cost, and its duration, through `core.llm`/`core.http` the same way P1/P2 do (CLAUDE.md rule 9).
- REQ-031: The zero-cost fail-safe (`FIN_AI_LAB_MAX_RUN_COST_USD=0`) applies to P3 runs exactly as it does to P1/P2 — any nonzero cost estimate stops the run rather than continuing silently.

MCP
- REQ-040 (AC-6): The system shall expose its data-reading tools through an MCP server so they can be used interactively from Claude Desktop or Claude Code, not only from the scheduled brief run (P3-S3 — contract defined now, per the same pattern P2 used for `XbrlClient` ahead of its own implementation slice).

Guardrails
- REQ-050 (AC-7): Before any fetched news text is sent to the model, the system shall pass it inside a delimited data section with an instruction that the section contains data, not instructions — same pattern as P1 REQ-007 / P2 REQ-003.
- REQ-051 (AC-7): If a news item contains text that addresses the model or resembles an instruction, then the system shall not let its content change the agent's tool use or output.
- REQ-052 (AC-8): The system shall not include a personalized investment recommendation (buy/sell/hold/increase/decrease) in the brief or an alert — same rule as P1/P2, ADR 0006.

## Business rules

Decyzja: reżim rynku

| Sygnał | Reguła (ASSUMPTION — wartości i wagi do kalibracji na realnych danych, patrz Open questions #3) |
|---|---|
| Krzywa rentowności (`T10Y2Y`) odwrócona | przechyla w stronę risk-off |
| VIX powyżej progu | przechyla w stronę risk-off |
| Brak sygnałów przekraczających próg | neutral |

Nie ustalam tu konkretnych wag i progów formuły — to decyzja Architekta/Dev, kalibrowana empirycznie (P3-S8 backtest), analogicznie do `refusal_threshold` w P2. Kontrakt: funkcja deterministyczna `wskaźniki -> (etykieta reżimu, lista sygnałów które o tym zdecydowały)`, wywoływana przed jakimkolwiek promptem do modelu.

Decyzja: alert czy cisza

| Którykolwiek skonfigurowany wskaźnik przekroczył swój próg zmiany | Wynik |
|---|---|
| tak | alert z opisem zmiany (REQ-020) |
| nie | brak alertu (REQ-021) |

## Data and validation

Obserwacja wskaźnika

| Field | Type | Required | Uwagi |
|---|---|---|---|
| `series_id` | string | tak | np. `DGS10`, `EUR/PLN` |
| `label` | string | tak | czytelna nazwa |
| `value` | Decimal | tak | |
| `unit` | string | tak | np. `%`, `PLN` |
| `as_of_date` | date | tak | dzień, którego dotyczy obserwacja (może być wcześniejszy niż dzień przebiegu — weekend/święto) |
| `source` | string | tak | `fred` / `nbp` / inne |
| `previous_value` | Decimal | nie | brak przy pierwszym przebiegu |
| `change` | Decimal | nie | `value - previous_value`, liczone w kodzie |

Brief

| Field | Type | Required |
|---|---|---|
| `date` | date | tak |
| `regime` | enum (`risk-on`/`neutral`/`risk-off`) | tak |
| `regime_rationale` | list[string] | tak — sygnały/wskaźniki, które zdecydowały (REQ-011) |
| `indicators` | list[IndicatorObservation] | tak |
| `missing_sources` | list[string] | tak — może być pusta |

Alert

| Field | Type | Required |
|---|---|---|
| `series_id` | string | tak |
| `previous_value` | Decimal | tak |
| `new_value` | Decimal | tak |
| `threshold` | Decimal | tak |
| `message` | string | tak |

## Edge and error cases

- Źródło danych niedostępne (sieć, limit, błąd API) — brief z resztą źródeł, źródło wymienione jako brakujące (REQ-002/013).
- Wskaźnik bez nowej obserwacji na dany dzień (weekend, święto, FRED/NBP nie publikują codziennie) — użyj najnowszej dostępnej obserwacji, nie generuj sztucznej wartości na ten dzień.
- Pierwszy przebieg (brak stanu z poprzedniego dnia) — brief bez `change`/alertów, nie błąd.
- News zawierający tekst przypominający polecenie dla modelu (prompt injection) — maskowanie/flagowanie jak w P1/P2 (REQ-050/051).
- Pytanie/żądanie o rekomendację inwestycyjną w interaktywnym użyciu MCP — odmowa z wyjaśnieniem (REQ-052, ADR 0006).
- WIG20 i inne dane rynkowe/komunikaty GPW wymagają płatnej licencji (`docs/DATA-SOURCES.md`) — nie ma darmowego, automatyzowalnego źródła znalezionego na etapie tej specyfikacji; patrz Open questions #1.

## Open questions

| # | Question | Owner | Due |
|---|---|---|---|
| 1 | WIG20: `docs/DATA-SOURCES.md` mówi, że dane rynkowe/komunikaty GPW wymagają płatnej licencji, a `yfinance` (REQ-004) nie może być użyty w automacie. Czy WIG20 wypada z MVP (Could, przegląd manualny), czy jest inne darmowe źródło do zweryfikowania przez Architekta? | Architect (weryfikacja źródła) / Tomasz (decyzja zakresu) | przed P3-S1 |
| 2 | Stopa referencyjna NBP: `api.nbp.pl` udokumentowane w `docs/DATA-SOURCES.md` dotyczy kursów walut i cen złota — Architekt musi zweryfikować, czy ta sama usługa (albo inna strona NBP) udostępnia stopę referencyjną w formie API, czy potrzebny jest scraping/dane ręczne. | Architect | przed P3-S1 |
| 3 | Formuła reżimu i progi alertów (Business rules powyżej) — wartości startowe ASSUMPTION, dokładna kalibracja empiryczna. Kiedy i na jakich danych historycznych kalibrować (przed P3-S1 z grubsza, czy dopiero w P3-S8 backtest)? | Architect | P3-S1 (start) / P3-S8 (kalibracja) |
| 4 | Kanał alertu (e-mail/webhook/plik) — pytanie ze `01-story.md` #1, wciąż otwarte, potrzebne przed P3-S5, nie blokuje wcześniejszych slice'ów. | Tomasz | przed P3-S5 |
