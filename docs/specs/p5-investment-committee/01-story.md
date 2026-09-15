# p5-investment-committee - Komitet inwestycyjny: wielu agentów nad portfelem

Status: Ready for ba
Owner role: PO
Upstream: -
Links: docs/ROADMAP.md, docs/adr/0006-descriptive-reports-no-investment-advice.md

## Problem

Pojedyncza analiza portfela łatwo pomija perspektywy — fundamenty, makro, sentyment, scenariusze stresowe — i nie mierzy się z kontrargumentami. Wcześniejsze tezy nie są rozliczane z tym, co się wydarzyło. Dla właściciela to projekt nauki orkestracji wielu agentów, context engineeringu, pamięci i human-in-the-loop, a także sprawdzenia, czy podejście multi-agent jest warte swojego kosztu.

## Outcome

Primary metric: komitet wygrywa porównanie parami z pojedynczym agentem przy tym samym budżecie w ≥ 60% portfeli testowych — albo dane pokazują, że nie warto (to też wynik nauki).
Guardrail metric: ≥ 95% twierdzeń w raporcie ma poprawne źródło; koszt przebiegu ≤ 1 USD (ASSUMPTION).

## User story

Jako inwestor chcę, żeby mój portfel został przeanalizowany z kilku perspektyw, z jawnymi rozbieżnościami i kontrargumentami, żeby lepiej rozumieć ryzyka, zanim sam podejmę decyzję.

## Acceptance criteria

- AC-1: Given portfel zaimportowany w P1, when uruchamiam komitet, then raport zawiera perspektywy fundamentalną, makro, sentymentu i scenariuszy stresowych oraz kontrargumenty.
- AC-2: Given rozbieżne wnioski perspektyw, when raport powstaje, then rozbieżności są wymienione jawnie z poziomem pewności.
- AC-3: Given dowolne twierdzenie w raporcie, when je sprawdzam, then wskazuje ono źródło: wynik narzędzia, fragment sprawozdania albo metrykę.
- AC-4: Given przebieg sprzed co najmniej miesiąca, when uruchamiam komitet ponownie, then raport rozlicza wcześniejsze tezy z tym, co się wydarzyło.
- AC-5: Given plan analizy, którego szacowany koszt przekracza limit, when komitet ma kontynuować, then najpierw prosi o akceptację.
- AC-6: Given scenariusz stresowy (np. akcje −20%, stopy +200 pb, PLN −15%), when raport go opisuje, then wynik scenariusza pochodzi z obliczeń w kodzie.
- AC-7: Given dowolny portfel, when raport powstaje, then nie zawiera rekomendacji inwestycyjnych.
- AC-8: Given ten sam budżet, when porównuję komitet z pojedynczym agentem, then raport porównawczy pokazuje jakość, koszt i czas obu wariantów.

## Out of scope

- Składanie zleceń, rekomendacje, analiza w czasie rzeczywistym.
- Produkcyjny interfejs — ewentualny prototyp UI później.

## Priority

Should, po P1–P4 (do testów wystarczą atrapy ich wyników). MVP cut line: P5-S1, P5-S2, P5-S4, P5-S7. Pozostałe — Should.

## Slices

| Slice | Wartość dla użytkownika | Czego uczy |
|---|---|---|
| P5-S1 Pojedynczy agent ze wszystkimi narzędziami | punkt odniesienia | baseline dla multi-agent |
| P5-S2 Supervisor + role-subagenci | wiele perspektyw | delegowanie, briefy, context engineering |
| P5-S3 Kwant ze stress testami | scenariusze w liczbach | code execution / sandbox |
| P5-S4 Krytyk i wymóg źródeł | weryfikowalne twierdzenia | evaluator-optimizer |
| P5-S5 Pamięć tez | rozliczanie przeszłych wniosków | pamięć długoterminowa, Brier score |
| P5-S6 Akceptacje i budżety | kontrola kosztu i przebiegu | human-in-the-loop, limity |
| P5-S7 A/B komitet vs pojedynczy agent | decyzja, czy warto | porównanie parami, koszt vs jakość |

## Dependencies and risks

- Korzysta z wyników P1 (portfel), P2 (RAG), P3 (brief), P4 (klasyfikator); do czasu ich ukończenia — atrapy.
- Historia cen do stress testów: yfinance, tylko lokalnie.
- Wielu agentów to wielokrotny koszt; ryzyko, że jakość nie wzrośnie.
- Pętle agentów bez warunków stopu mogą wydać budżet.

## Open questions

| # | Question | Owner | Due |
|---|---|---|---|
| 1 | Portfele testowe: syntetyczne (np. 10 profili) czy zanonimizowany własny? | Tomasz | przed P5-S1 |
| 2 | Czy Managed Agents (beta) wchodzi jako dodatkowy wariant porównawczy? | Tomasz | przed P5-S7 |
| 3 | Akceptacje human-in-the-loop: w CLI czy w prostym UI? | Tomasz | przed P5-S6 |
