# portfolio-webapp - Portfolio Web App: portfel inwestycyjny jako aplikacja webowa nad P1/P3

Status: Ready for architect
Owner role: PO
Upstream: -
Links: docs/ROADMAP.md, docs/ARCHITECTURE.md, docs/specs/p1-portfolio-xray/, docs/specs/p3-market-pulse/

## Problem

Portfel dziś istnieje tylko jako jednorazowe wywołanie CLI (`fin-ai-lab portfolio-xray ...`) — wgranie pliku i raport w jednej sesji terminala, bez zapisu stanu między uruchomieniami. Właściciel chce widzieć portfel na bieżąco: wiele brokerów, wiele importów w czasie, ręcznie dodane pozycje, metryki i raport AI dostępne bez powtarzania całego CLI za każdym razem.

To też krok w stronę kierunku zapowiedzianego w README.md i ROADMAP.md (funkcja portfela w Analizotece, z analizą AI z tego repo jako ważnym elementem). W odróżnieniu od tamtego kierunku ten epik zostaje w całości w fin-ai-lab: narzędzie jednoosobowe do nauki, nie produkt, bez uwierzytelniania i bez hostingu poza localhost. Ewentualne przeniesienie czy integracja z Analizoteką (osobne repo, .NET 10 + React 19) to osobna decyzja poza zakresem tego epiku.

P1 (`portfolio_xray`) sam w sobie nie zyskuje interfejsu graficznego — zostaje tym, czym jest dziś (CLI i raport w markdown, `01-story.md`'s Out of scope). Ten epik konsumuje P1 jako bibliotekę przez `service.py`, na tej samej zasadzie, na jakiej dziś robi to P5 (`investment_committee`).

## Outcome

Primary metric: właściciel wgrywa eksport XTB, widzi zaimportowany portfel i generuje raport AI wyłącznie w przeglądarce, bez użycia terminala, w jednej sesji.
Guardrail metric: 0 raportów bez widocznego w interfejsie zastrzeżenia „opis, nie rekomendacja"; 0 rozbieżności między pozycjami/metrykami pokazanymi w przeglądarce a tym, co zwróciłoby CLI dla tego samego pliku.

## User story

Jako inwestor z kontami u kilku brokerów chcę wgrywać eksporty i ręcznie dodawać pozycje w przeglądarce, widzieć aktualny portfel z metrykami i mieć na żądanie raport AI, żeby nie musieć za każdym razem odpalać CLI i pamiętać poprzednich wyników.

## Acceptance criteria

- AC-1: Given plik XTB w formacie już rozpoznawanym przez P1, when wgrywam go przez przeglądarkę, then widzę zaimportowane pozycje bez użycia terminala.
- AC-2: Given portfel po imporcie, when otwieram jego stronę, then widzę alokację, koncentrację i ekspozycję walutową policzone tymi samymi funkcjami co CLI (P1's `metrics`), nie przeliczone od nowa.
- AC-3: Given zaimportowany portfel, when klikam „generuj raport”, then dostaję raport AI z tym samym guardrailem braku rekomendacji i stopką edukacyjną co P1's CLI, plus stały, widoczny w interfejsie disclaimer.
- AC-4: Given portfel bez żadnego pliku, when dodaję pozycję ręcznie (instrument, ilość, koszt), then pozycja liczy się do metryk tak samo jak pozycja zaimportowana z pliku.
- AC-5: Given portfel z wcześniejszym importem, when wgrywam nowy plik tego samego brokera, then poprzedni stan nie znika — widzę kolejny punkt w czasie, nie nadpisanie.
- AC-6: Given plik z podejrzaną komórką (P1's REQ-008), when go wgrywam przez przeglądarkę, then ostrzeżenie zostaje widoczne w interfejsie, nie ginie po drodze przez warstwę API.
- AC-7: Given appka uruchomiona lokalnie, when ktoś próbuje się z nią połączyć spoza tej maszyny, then nie dostaje odpowiedzi — serwer nasłuchuje wyłącznie na localhost, bez uwierzytelniania jako jedynej warstwy ochrony.
- AC-8: Given zaimportowane lub ręcznie dodane pozycje, when tworzę agregat i przypisuję do niego dowolne instrumenty i/lub inne agregaty, then widzę sumę ich wartości w walucie bazowej jako wartość agregatu.
- AC-9: Given agregat, który pośrednio (przez zagnieżdżony agregat) obejmuje ten sam instrument dwiema różnymi ścieżkami, when patrzę na jego wartość, then instrument liczy się raz, nie wielokrotnie.
- AC-10: Given próba dodania do agregatu jego samego — bezpośrednio albo przez łańcuch zagnieżdżeń, when zapisuję zmianę, then system odmawia z czytelnym komunikatem i cykl nie powstaje.

## Out of scope

- Uwierzytelnianie i wielu użytkowników — narzędzie jednoosobowe; społeczność i konta to domena Analizoteki, nie fin-ai-lab.
- Import Bossy przez tę appkę, dopóki nie powstanie osobny ticket w P1 (agregacja historii transakcji do pozycji, `hisPW.csv` nie jest eksportem stanu portfela). Ten epik konsumuje gotową zdolność P1, nie buduje jej.
- Panel danych rynkowych z P3 i wgląd w komitet inwestycyjny z P5 — later, jak w ROADMAP.md.
- Pełne rozliczenie transakcyjne (XIRR, podatki, FIFO/PIT-38) — jak w P1's `01-story.md`, later.
- Hosting poza localhost, wdrożenie produkcyjne, przeniesienie lub integracja z Analizoteką — osobna decyzja, osobne repo.

## Priority

Must: portfolio-webapp-S1 do portfolio-webapp-S6 (szkielet, import XTB, nieznany format, ręczne pozycje, metryki/wykresy, raport AI). Should: portfolio-webapp-S7 (historia w czasie), portfolio-webapp-S9 (agregaty). Bossa (portfolio-webapp-S8): zależna od osobnego ticketu w P1, nie wchodzi do MVP tego epiku.

## Slices

| Slice | Wartość dla użytkownika | Czego uczy |
|---|---|---|
| portfolio-webapp-S1 Szkielet | appka chodzi lokalnie w ogóle | FastAPI/DuckDB na tej maszynie; granica modułu jak P5→P1 |
| portfolio-webapp-S2 Import XTB przez UI | koniec z terminalem dla znanego brokera | wystawienie istniejącej logiki P1 jako API |
| portfolio-webapp-S3 Nieznany format w UI | nowy broker o kształcie „pozycje w wierszu” bez pisania kodu z palca | webowy odpowiednik `typer.confirm` (propose/approve) |
| portfolio-webapp-S4 Ręczne pozycje | portfel bez pliku wcale | CRUD nad `canonical.Position` |
| portfolio-webapp-S5 Metryki i wykresy | portfel widać, nie trzeba czytać JSON-a | wizualizacja tego, co P1 już liczy |
| portfolio-webapp-S6 Raport AI na żądanie | opis portfela bez CLI | reużycie `report/orchestrator.py`, cache per snapshot |
| portfolio-webapp-S7 Historia w czasie | widać zmianę portfela, nie tylko bieżący stan | zapytania po snapshotach w DuckDB |
| portfolio-webapp-S8 Import Bossy | drugi broker naprawdę działa | konsumpcja nowego ticketu P1 (ledger → pozycje) |
| portfolio-webapp-S9 Agregaty | dowolne grupowanie instrumentów (np. łączna ekspozycja na BTC przez ETF i wprost), zagnieżdżone | drzewiaste struktury zdefiniowane przez użytkownika, wykrywanie cykli, deduplikacja przy sumowaniu |

## Dependencies and risks

- Wymaga gotowego P1 (`portfolio_xray`): import, metryki, raport, reużywane przez `service.py`, tym samym wzorcem co P5.
- Bossa wymaga osobnego ticketu w P1 (agregacja transakcji: dedup po hashu wiersza, pełny replay zamiast merge gotowych pozycji) — portfolio-webapp-S8 nie zaczyna się, dopóki ten ticket nie jest gotowy.
- DuckDB: brak AVX2 na maszynie deweloperskiej — test importu w portfolio-webapp-S1 przed dalszą architekturą, ten sam dryl co przy każdej nowej zależności natywnej w tym repo.
- yfinance: `docs/DATA-SOURCES.md` oznacza je jako tylko lokalnie, nie do produktu — appka zostaje bez uwierzytelniania i bez hostingu poza localhost także z tego powodu, nie tylko dla prostoty.
- Dzienny limit zapytań Gemini współdzielony z P2–P5: web UI ułatwia wielokrotne „generuj raport”. `FIN_AI_LAB_MAX_RUN_COST_USD` dziś pilnuje tylko przebiegów evali, nie tej ścieżki — portfolio-webapp-S6 cache'uje ostatni raport per snapshot, żeby nie zużywać limitu bez potrzeby.
- Nie rozszerza kodu P1 — P1 zostaje CLI-only; ten epik żyje w osobnym pakiecie (`portfolio_webapp/`) i osobnym `frontend/`, wołając wyłącznie publiczne funkcje P1.
- Agregaty (portfolio-webapp-S9) to struktura zdefiniowana przez użytkownika, nie derywowana z danych brokera — wymaga wykrywania cykli przy zapisie (AC-10) i deduplikacji instrumentu przy sumowaniu wartości, gdy jest osiągalny dwiema ścieżkami (AC-9). Członkostwo instrumentu w agregacie musi być kluczowane stabilnym identyfikatorem (ISIN, w jego braku broker+symbol), nie id wiersza pozycji z konkretnego snapshotu — inaczej agregat przestawałby działać po każdym ponownym imporcie.

## Open questions

| # | Question | Owner | Status |
|---|---|---|---|
| 1 | ~~Czy Bossa daje eksport stanu portfela, czy tylko historię transakcji?~~ | Tomasz | Odpowiedź: tylko historia transakcji (`hisPW.csv`), zakres dat wybierany ręcznie, zachodzenie dozwolone — osobny ticket w P1 (dedup po hashu wiersza + pełny replay) |
| 2 | Nazwa i branding appki | Tomasz | otwarte, nieblokujące |
| 3 | Czy portfolio-webapp-S7 (historia w czasie) wystarcza, czy od razu potrzebne pełne rozliczenie transakcyjne (XIRR)? | Tomasz | otwarte, przed S7 |
