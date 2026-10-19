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
- AC-11: Given kilka portfeli, when otwieram appkę, then pierwszy ekran pokazuje sumę wszystkich portfeli w PLN według notowań pobranych przy wejściu na ekran, udział każdego portfela i jedną tabelę wszystkich aktywów.
- AC-12: Given portfel (albo widok zbiorczy), when patrzę na wykres, then widzę wartość **dzień po dniu** — dzienny kurs zamknięcia razy liczba sztuk posiadana tego dnia — a nie tylko punkty w dniach importów.
- AC-13: Given pozycje portfela, when patrzę na tabelę, then każdy wiersz pokazuje aktywo, cenę zakupu, cenę bieżącą, liczbę sztuk, wartość pozycji i stopę zwrotu; informacja o imporcie jest drugorzędna (przy formularzu importu).
- AC-14: Given eksport XTB z datami otwarcia pozycji, when go importuję, then historia wartości zaczyna się od daty pierwszego zakupu, a nie od dnia importu.
- AC-15: Given portfel (albo widok zbiorczy), when wybieram podział, then widzę wykres kołowy udziałów jego grup i aktywów w bieżącej wartości oraz tabelę z wartością, udziałem w grupie i udziałem w portfelu.
- AC-16: Given kilka własnych podziałów (np. Strategia, Region, Ryzyko), when przypisuję to samo aktywo w każdym z nich, then może ono być w innej grupie w każdym podziale, ale w jednym podziale tylko w jednej grupie — udziały zawsze sumują się do 100%.
- AC-17: Given grupa z podgrupami, when klikam ją na wykresie albo w tabeli, then widzę udziały wewnątrz tej grupy i jaki procent całego portfela stanowi; ścieżka pozwala wrócić wyżej.
- AC-18: Given próba przeniesienia grupy do niej samej albo do jej podgrupy, when zapisuję, then system odmawia z czytelnym komunikatem.
- AC-19: Given brak konfiguracji, when otwieram udziały, then mam od razu podziały wbudowane: aktywa, klasa aktywów, waluta notowań i (w widoku zbiorczym) portfel.
- AC-20: Given ta sama spółka albo fundusz kupiony u dwóch brokerów (np. XTB bez ISIN i Bossa z ISIN), when oba importy rozpoznały to samo notowanie (ten sam FIGI), then to jedno aktywo — jeden wiersz w tabeli aktywów, jeden wycinek w udziałach, jedno miejsce w każdym podziale.
- AC-21: Given para instrumentów, których dane nie przesądzają (ten sam ticker albo podobna nazwa przy podobnej cenie za sztukę), when otwieram appkę, then widzę informację o parze do potwierdzenia, a w formularzu „Łączenie instrumentów” potwierdzam „to ten sam” albo „to różne”; do czasu decyzji liczą się osobno, nic nie łączy się samo.
- AC-22: Given instrument, którego odpowiednika system nie zaproponował, when wskazuję go ręcznie w formularzu, then oba stają się jednym aktywem; when odłączam instrument, then wraca jako osobne aktywo, a reszta połączenia zostaje.
- AC-23: Given zaimportowane wypłaty dywidend (arkusz Cash Operations z XTB, historia finansowa Bossy), when otwieram stronę portfela albo widok zbiorczy, then widzę sumę wypłat w PLN łącznie, w bieżącym roku i w ostatnich 12 miesiącach, wykres po latach (i po miesiącach wybranego roku) oraz tabelę instrumentów z liczbą wypłat, ostatnią wypłatą i sumą.
- AC-24: Given te same wypłaty, when porównuję sumę historii dywidend z kwotą „dywidendy” w wyniku inwestycji, then obie są równe co do grosza.
- AC-25: Given wypłata, której nie da się przypisać do instrumentu, when patrzę na historię, then liczy się do sum pod nazwą z wyciągu i jest oznaczona jako nieprzypisana.
- AC-26: Given pozycje trzymane dziś, when otwieram zakładkę „Szacunek”, then widzę szacunek dywidend brutto na następny rok kalendarzowy: sumę, kwoty po miesiącach i tabelę instrumentów (liczba sztuk, kwota na akcję z ostatnich 12 miesięcy, stopa dywidendy, źródło danych), ze stałym dopiskiem, że to opis, nie prognoza ani rekomendacja.
- AC-27: Given instrument, którego Yahoo nie zna, when liczę szacunek, then system bierze kwoty na akcję z wyciągu XTB; when Yahoo i wyciąg różnią się o ponad 25% na jedną wypłatę, then instrument ma flagę rozbieżności.
- AC-28: Given portfel z ustawionym typem konta, when patrzę na szacunek, then obok kwoty brutto widzę kwotę na konto (po podatku pobieranym przed wypłatą) i stawkę ze źródłem (wyciąg albo reguła); na IKE i IKZE polska spółka nie płaci podatku, a zagraniczna tylko podatek u źródła; na koncie zwykłym dopłata do 19% w zeznaniu jest pokazana osobno, nie odjęta (#267).
- AC-29: Given portfel (albo widok zbiorczy), when wybieram na wykresie tryb „Porównanie” i benchmark (wbudowany albo dowolny ticker Yahoo), then widzę dwie linie w % od początku wybranego zakresu — zwrot portfela, którego nie zmieniają wpłaty, wypłaty, zakupy ani sprzedaże, i zwrot benchmarku w PLN — oraz różnicę w punktach procentowych; obie strony zawierają dywidendy (#273).
- AC-30: Given portfel, którego import nie ma operacji gotówkowych, when porównuję go z benchmarkiem, then widzę uwagę, że jego zwrot jest bez dywidend; given ticker, którego Yahoo nie zna, then widzę czytelny komunikat, a wykres portfela działa dalej.
- AC-31: Given portfele ze znanymi wpłatami i wypłatami, when otwieram tryb „Porównanie”, then pierwsza liczba to mój wynik inwestycji w zł i w % wpłat, a obok wynik tych samych wpłat (te same kwoty, te same dni) wpłaconych do benchmarku i różnica w zł — niezależnie od zakresu wykresu.
- AC-32: Given instrumenty bez dziennych notowań, when patrzę na porównanie, then widzę, ile z wyniku inwestycji obejmuje wykres w % i jaka część wartości nie ma dziennych notowań; gdy wykres pomija ponad 10% wyniku, informacja jest ostrzeżeniem.
- AC-33: Given instrument z historii Bossy — także sprzedany albo niejednoznaczny w OpenFIGI — when importuję plik, then na wykresie jego wartość zmienia się dzień po dniu razem z kursem notowania dobranego do waluty transakcji; instrument, dla którego takiego notowania nie ma, zachowuje stałą wartość z ostrzeżeniem jak dotąd (#277).
- AC-34: Given instrument bez dziennych notowań albo z nieznaną walutą notowania (np. akcja z USA kupiona w PLN na Bossie), when na ekranie instrumentów wpisuję jego symbol z Yahoo i walutę notowania, then jego wartość na wykresie i w tabeli od razu zmienia się razem z notowaniami tego symbolu i kursem tej waluty, bez ponownego importu; symbolu, którego Yahoo nie zna, system nie zapisuje i mówi dlaczego; wpis mogę usunąć i wtedy wraca to, co ustalił import (#285).
- AC-35: Given aktywo nienotowane na giełdzie (np. złota moneta), when dodaję je ręcznie z datą zakupu (domyślnie dziś) i ceną zakupu za sztukę, then od daty zakupu widzę je na wykresie po cenie zakupu, a wynik inwestycji i porównanie wpłat liczą zakup tego dnia; data zakupu z przyszłości jest odrzucona z czytelnym komunikatem (#288).
- AC-36: Given ręczna pozycja, when dopisuję wycenę (dzień i cena za sztukę), then od dnia wyceny jej wartość na wykresie, w tabeli pozycji, w metrykach i w udziałach to ta wycena, a do niego cena zakupu albo poprzednia wycena — bez wymyślania wartości pomiędzy; wycena sprzed zakupu albo z przyszłości jest odrzucona z czytelnym komunikatem; usunięcie wyceny przywraca poprzednią (#288).

## Out of scope

- Uwierzytelnianie i wielu użytkowników — narzędzie jednoosobowe; społeczność i konta to domena Analizoteki, nie fin-ai-lab.
- Import Bossy przez tę appkę, dopóki nie powstanie osobny ticket w P1 (agregacja historii transakcji do pozycji, `hisPW.csv` nie jest eksportem stanu portfela). Ten epik konsumuje gotową zdolność P1, nie buduje jej.
- Panel danych rynkowych z P3 i wgląd w komitet inwestycyjny z P5 — later, jak w ROADMAP.md.
- Pełne rozliczenie transakcyjne (XIRR, podatki, FIFO/PIT-38) — jak w P1's `01-story.md`, later.
- Hosting poza localhost, wdrożenie produkcyjne, przeniesienie lub integracja z Analizoteką — osobna decyzja, osobne repo.

## Priority

Must: portfolio-webapp-S1 do portfolio-webapp-S6 (szkielet, import XTB, nieznany format, ręczne pozycje, metryki/wykresy, raport AI). Should: portfolio-webapp-S7 (historia w czasie), portfolio-webapp-S9 (agregaty), portfolio-webapp-S10 (widok zbiorczy i dzienna historia wartości — realizuje też cel S7 dokładniej niż punkty w dniach importów), portfolio-webapp-S11 (udziały i podziały), portfolio-webapp-S12 (jedno aktywo u wielu brokerów). Bossa (portfolio-webapp-S8): zależna od osobnego ticketu w P1, nie wchodzi do MVP tego epiku.

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
| portfolio-webapp-S11 Udziały i podziały | wykres kołowy udziałów z drążeniem w grupy, kilka własnych podziałów z zagnieżdżanymi grupami, podziały wbudowane bez konfiguracji | drzewo z wymuszoną rozłącznością (klucz w bazie, nie w kodzie UI), walidacja cykli przy przenoszeniu grup, wykres części całości zgodnie z zasadami dataviz |
| portfolio-webapp-S12 Jedno aktywo u wielu brokerów | ta sama spółka z XTB i z Bossy to jedno aktywo w tabeli, udziałach i podziałach; formularz do potwierdzenia albo wskazania pary | tożsamość encji z kilku źródeł (FIGI jako klucz, union-find), człowiek w pętli tam, gdzie dane nie przesądzają |
| portfolio-webapp-S10 Widok zbiorczy i dzienna historia | suma wszystkich portfeli na starcie, wykres wartości dzień po dniu (zbiorczo i per portfel), tabela aktywów z ceną zakupu/bieżącą i zwrotem | szereg czasowy z dwóch niezależnych źródeł (ilość × cena), ratio zamiast absolutnej ceny obcej (#188), serie kursów NBP w oknach, projekt w Claude Design → kod |
| portfolio-webapp-S13 Dywidendy (#265 historia, #266 szacunek) | ile dywidend wpłynęło — po latach, miesiącach i instrumentach, dla portfela i zbiorczo; szacunek na następny rok kalendarzowy | łączenie wierszy z wyciągu w jedną wypłatę, przypisanie do instrumentu z kilku źródeł (ticker, nazwa, OpenFIGI), test zgodności z istniejącą liczbą (wynik inwestycji) jako strażnik |
| portfolio-webapp-S14 Porównanie z benchmarkiem (#273) | czy portfel zarobił więcej czy mniej niż rynek (WIG20, S&P 500, dowolny ticker), w % i na wykresie, z dywidendami po obu stronach | zwrot ważony czasem (time-weighted) — jak oddzielić wynik inwestowania od wpłat; indeksy cenowe a „total return”; brak historii indeksów GPW w Yahoo i zastępstwo funduszem ETF |

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
