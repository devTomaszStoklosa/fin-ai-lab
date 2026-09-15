# p3-market-pulse - Market Pulse: agent kondycji rynku

Status: Ready for ba
Owner role: PO
Upstream: -
Links: docs/ROADMAP.md, docs/DATA-SOURCES.md

## Problem

Stan rynku jest rozproszony: stopy procentowe, krzywa rentowności, kursy walut, indeksy, newsy, kalendarz publikacji. Codzienne przeglądanie źródeł zajmuje czas, a istotną zmianę łatwo przeoczyć. Dla właściciela to projekt nauki projektowania narzędzi, różnicy między workflow a agentem, MCP, observability i kontroli kosztów.

## Outcome

Primary metric: brief gotowy przed 8:00 w ≥ 95% dni roboczych, koszt przebiegu < 0,10 USD (ASSUMPTION).
Guardrail metric: 0 liczb w briefie niezgodnych z danymi z narzędzi; precyzja alertów oceniana ręcznie ≥ 80%.

## User story

Jako inwestor chcę codziennie rano dostać krótki brief o kondycji rynku z informacją, co zmieniło się od wczoraj, żeby nie przeoczyć istotnej zmiany bez przeglądania wielu źródeł.

## Acceptance criteria

- AC-1: Given dostępne dane makro, rynkowe i newsy, when przebieg się kończy, then brief zawiera stan wskaźników, ocenę reżimu (risk-on / neutral / risk-off) z uzasadnieniem i listę zmian od poprzedniego przebiegu.
- AC-2: Given niedostępne źródło danych, when przebieg trwa, then brief powstaje z pozostałych źródeł i wymienia brakujące.
- AC-3: Given zmiana wskaźnika przekraczająca próg reguły, when przebieg się kończy, then wysyłany jest alert z opisem zmiany.
- AC-4: Given brak istotnych zmian, when przebieg się kończy, then alert nie jest wysyłany.
- AC-5: Given dowolny przebieg, when się kończy, then dostępny jest trace z wywołaniami narzędzi, kosztem i czasem.
- AC-6: Given narzędzia danych udostępnione przez serwer MCP, when podłączam go do Claude Desktop lub Claude Code, then mogę z nich korzystać interaktywnie.
- AC-7: Given newsy zawierające polecenia dla modelu, when trafiają do kontekstu, then nie zmieniają zachowania agenta.
- AC-8: Given brief, when go czytam, then nie zawiera rekomendacji inwestycyjnych.

## Out of scope

- Jakiekolwiek zlecenia i narzędzia z zapisem u brokera — agent ma wyłącznie narzędzia do odczytu.
- Dane intraday i prognozy cen.
- Interfejs graficzny.

## Priority

Should. MVP cut line: P3-S1 do P3-S3 oraz P3-S5. Pozostałe slice'y — Should.

## Slices

| Slice | Wartość dla użytkownika | Czego uczy |
|---|---|---|
| P3-S1 Wskaźniki w kodzie + jedno wywołanie LLM | pierwszy brief | workflow (prompt chaining), kod liczy |
| P3-S2 Narzędzia + tool runner | agent sam dobiera dane | projekt narzędzi, pętla tool use |
| P3-S3 Serwer MCP | te same dane w Claude Desktop / Code | protokół MCP |
| P3-S4 Orchestrator-workers | szybszy i szerszy brief | równoległe workery, synteza |
| P3-S5 Stan i alerty | informacja tylko o istotnych zmianach | pamięć między przebiegami, reguły progów |
| P3-S6 Tracing i koszty | wiadomo, ile kosztuje i co robi agent | observability, prompt caching, Batch API |
| P3-S7 Harmonogram | brief bez ręcznego uruchamiania | Task Scheduler / GitHub Actions / Managed Agents |
| P3-S8 Evale trajektorii i backtest | zaufanie do oceny reżimu | eval agentów, look-ahead bias |

## Dependencies and risks

- Wymaga `lab-foundation`; klucz FRED.
- Licencje serii FRED: część (np. `VIXCLS`) tylko do nauki.
- GDELT DOC API: 1 żądanie na 5 s i ryzyko bana IP — tylko ad hoc.
- yfinance jest nieoficjalne i bywa blokowane.
- Backtest na historii: model „zna" przeszłe wydarzenia z danych treningowych — wymagana anonimizacja dat albo okresy po knowledge cutoff.
- Harmonogram lokalny wymaga włączonego komputera.

## Open questions

| # | Question | Owner | Due |
|---|---|---|---|
| 1 | Kanał alertu: e-mail, webhook (np. Discord) czy plik? | Tomasz | przed P3-S5 |
| 2 | Harmonogram: Task Scheduler, GitHub Actions czy Managed Agents? | Tomasz | przed P3-S7 |
| 3 | Priorytetowe wskaźniki PL (WIG20, EUR/PLN, USD/PLN, stopy NBP)? | Tomasz | przed P3-S1 |
