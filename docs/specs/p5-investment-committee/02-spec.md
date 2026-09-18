# p5-investment-committee - Specification

Status: Ready for architect
Owner role: BA
Upstream: 01-story.md

## Glossary

| Term | Meaning |
|---|---|
| Komitet | zestaw subagentów-specjalistów koordynowanych przez supervisora, analizujący jeden portfel |
| Supervisor | agent dzielący zadanie na perspektywy, zbierający briefy subagentów, składający raport (docs/LEARNING.md: orchestrator-workers) |
| Perspektywa | jeden punkt widzenia na portfel: fundamentalna, makro, sentymentu, scenariuszy stresowych |
| Brief | ustrukturyzowany wynik jednego subagenta, wejście do raportu końcowego |
| Krytyk | subagent oceniający briefy innych pod kątem wymogu źródeł, w pętli evaluator-optimizer |
| Teza | konkretne stwierdzenie o portfelu z poprzedniego przebiegu, podlegające rozliczeniu w kolejnym |
| Rozliczenie tezy | porównanie tego, co teza przewidywała, z tym, co faktycznie się wydarzyło (Brier score) |
| Scenariusz stresowy | hipotetyczny szok rynkowy (np. akcje -20%) z policzonym w kodzie wpływem na portfel |
| Budżet | limit kosztu USD na przebieg komitetu, wymagający akceptacji przy przekroczeniu |

## Actors and permissions

| Actor | Action | Allowed |
|---|---|---|
| Właściciel | uruchamia komitet, akceptuje przekroczenie budżetu, czyta raport | tak |
| Supervisor (LLM) | dzieli zadanie na perspektywy, zleca subagentom, składa raport z ich briefów | tak — tylko synteza, nigdy własna niezależna klasyfikacja liczb |
| Subagent-perspektywa (LLM) | pisze brief ze swojej perspektywy, na podstawie narzędzi i danych | tak — tylko z podanych danych, z cytatem/źródłem na każde twierdzenie |
| Krytyk (LLM) | ocenia briefy pod kątem wymogu źródeł, odsyła do poprawy | tak — ocena, nie generuje nowych twierdzeń |
| Kwant (kod, nie LLM) | liczy scenariusze stresowe na realnych metrykach portfela | tak — deterministyczne obliczenia, żaden wynik liczbowy nie pochodzi z LLM |
| Narzędzia P1-P4 | portfel, RAG sprawozdań, brief rynkowy, klasyfikacja newsów | tak — tylko odczyt; atrapa dopóki dany projekt nie jest gotowy (01-story.md dependency) |

## Functional requirements (EARS)

Perspektywy i raport
- REQ-001 (AC-1): The system shall include, for every committee run, a fundamental perspective, a macro perspective, a sentiment perspective, and a stress-scenario perspective in the final report.
- REQ-002 (AC-2): When perspectives disagree on a conclusion about the portfolio, the system shall state the disagreement explicitly in the report, together with each perspective's confidence level — never silently pick one side.
- REQ-003 (AC-3): Every claim in the report shall carry a source: a tool result, a filing excerpt (P2), or a computed metric — never an unsourced assertion.
- REQ-004: The supervisor shall never independently compute or restate a numeric result a subagent already produced — it synthesizes briefs, it does not recompute their numbers (CLAUDE.md rule 2, mirrors P3's regime-classification boundary).

Rozliczanie tez
- REQ-010 (AC-4): When a committee run starts and a prior run (≥1 month old) exists for the same portfolio, the system shall include a reckoning of that prior run's theses against what actually happened since, with each thesis marked accurate, inaccurate, or not yet resolvable.
- REQ-011: The system shall track thesis accuracy over time using a Brier score (or equivalent calibration metric) per subagent perspective, so persistent over/under-confidence is visible, not just per-run wins/losses.

Budżet i kontrola
- REQ-020 (AC-5): When the committee's estimated cost for continuing exceeds the configured budget, the system shall stop and request explicit approval before spending further — never continue silently past the limit (mirrors CLAUDE.md rule 9's zero-cost fail-safe, applied per-run here instead of per-key).
- REQ-021: The system shall enforce a hard stop condition on every agent loop (max iterations or max cost), so an agent that fails to converge cannot silently exhaust the budget (01-story.md risk).

Scenariusze stresowe
- REQ-030 (AC-6): The system shall compute every stress-scenario result (e.g. equities -20%, rates +200bp, PLN -15%) from portfolio data in code — never from a number the model generated (CLAUDE.md rule 2).

Guardrails
- REQ-040 (AC-7): The system shall not include a personalized investment recommendation (buy/sell/hold/increase/decrease) anywhere in the report — same rule as P1-P4, ADR 0006.
- REQ-041 (AC-3, guardrail): If a subagent's brief contains a claim without an identifiable source, the critic shall reject it and require a revision before it reaches the final report (evaluator-optimizer loop, docs/LEARNING.md).

Porównanie
- REQ-050 (AC-8): The system shall produce, for a fixed budget, a side-by-side comparison of the committee's output against a single-agent baseline (P5-S1) on quality, cost, and latency — not committee output alone.

## Business rules

Decyzja: komitet vs pojedynczy agent (metryka sukcesu z 01-story.md)

| Wynik porównania parami przy tym samym budżecie | Wniosek |
|---|---|
| Komitet wygrywa w ≥60% portfeli testowych | multi-agent uzasadnia swój koszt |
| Komitet wygrywa w <60% portfeli testowych | to też ważny wynik — nie ukrywać, nie przeciągać progu wstecz |

Decyzja: rozbieżność perspektyw

| Sytuacja | Wynik |
|---|---|
| Wszystkie perspektywy zgodne | jeden wniosek w raporcie |
| Perspektywy rozbieżne | rozbieżność wypisana jawnie, z poziomem pewności każdej strony (REQ-002) — supervisor nigdy nie wybiera "zwycięzcy" po cichu |

Decyzja: teza nierozliczalna

| Sytuacja | Wynik |
|---|---|
| Od tezy minął ≥1 miesiąc i zdarzenie już nastąpiło | rozliczona: trafna / nietrafna |
| Od tezy minął ≥1 miesiąc, ale horyzont tezy jest dłuższy (np. "w ciągu roku") | oznaczona "jeszcze nierozliczalna", nie wymuszona ocena przedwczesna |

## Data and validation

Brief subagenta

| Field | Type | Required | Uwagi |
|---|---|---|---|
| `perspective` | enum | tak | `fundamental` / `macro` / `sentiment` / `stress` |
| `conclusion` | string | tak | |
| `confidence` | float 0-1 | tak | REQ-002 |
| `claims` | list[Claim] | tak | każde twierdzenie z własnym źródłem (REQ-003) |

Claim (twierdzenie ze źródłem)

| Field | Type | Required | Uwagi |
|---|---|---|---|
| `text` | string | tak | |
| `source_type` | enum | tak | `tool_result` / `filing_excerpt` / `computed_metric` |
| `source_ref` | string | tak | identyfikator/cytat wystarczający do weryfikacji |

Teza (do rozliczenia, REQ-010/011)

| Field | Type | Required | Uwagi |
|---|---|---|---|
| `statement` | string | tak | |
| `made_at` | date | tak | |
| `horizon` | string | tak | np. "1 miesiąc", "1 rok" — decyduje o rozliczalności |
| `outcome` | enum | nie | `accurate` / `inaccurate` / `not_yet_resolvable`, wypełniane przy rozliczeniu |

Scenariusz stresowy

| Field | Type | Required | Uwagi |
|---|---|---|---|
| `name` | string | tak | np. "akcje -20%" |
| `shock` | dict | tak | parametry szoku per klasa aktywów |
| `portfolio_impact` | Decimal | tak | liczone w kodzie, nigdy przez LLM (REQ-030) |

## Edge and error cases

- Perspektywy rozbieżne bez jasnego zwycięzcy — rozbieżność jawna, nie uśredniona ani ukryta (REQ-002).
- Twierdzenie bez źródła w briefie subagenta — odrzucone przez krytyka, wymagana poprawka (REQ-041).
- Pierwszy przebieg dla portfela (brak wcześniejszych tez) — brak sekcji rozliczenia, nie błąd (analogiczne do P3-S5 "brak stanu = pierwszy przebieg").
- Teza z długim horyzontem, jeszcze nierozliczalna — oznaczona jawnie, nie wymuszona ocena (Business rules powyżej).
- Szacowany koszt kontynuacji przekracza budżet w trakcie przebiegu (nie tylko na starcie) — zatrzymanie i prośba o akceptację, nie tylko kontrola wstępna (REQ-020).
- Pętla agenta bez zbieżności — twardy stop po limicie iteracji/kosztu (REQ-021), nie nieskończone dopracowywanie.
- P1-P4 niegotowe w danym momencie rozwoju — atrapa wyników, jawnie oznaczona jako atrapa w raporcie, nie cicha fikcja (01-story.md dependency).

## Open questions

| # | Question | Owner | Due |
|---|---|---|---|
| 1 | Portfele testowe: syntetyczne (np. 10 profili) czy zanonimizowany własny? | Tomasz | przed P5-S1 |
| 2 | Czy Managed Agents (beta) wchodzi jako dodatkowy wariant porównawczy? | Tomasz | przed P5-S7 |
| 3 | Akceptacje human-in-the-loop: w CLI czy w prostym UI? | Tomasz | przed P5-S6 |
| 4 | Format pamięci tez (REQ-010/011) — plik JSON per portfel (wzorzec P3 `state.py`) czy coś bogatszego (np. baza z historią zmian)? | Architect | przed P5-S5 |
