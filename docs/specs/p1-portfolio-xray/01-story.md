# p1-portfolio-xray - Portfolio X-Ray: import eksportu z brokera i raport opisowy

Status: Ready for architect
Owner role: PO
Upstream: -
Links: docs/ROADMAP.md, docs/specs/lab-foundation/

## Problem

Inwestor indywidualny trzyma pozycje u kilku brokerów (XTB, mBank, Bossa, IBKR, Trading212, Revolut). Każdy eksportuje inny format: CSV, XLSX albo PDF, nagłówki po polsku lub angielsku, różne formaty liczb i dat. Obraz całości — koncentracja, waluty, ryzyko — wymaga ręcznego klejenia arkuszy. Dla właściciela repo to projekt nauki: structured outputs, walidacja z pętlą samokorekty, pierwsze narzędzie, evale wierności. Właściciel ma konta u XTB i Bossa (Dom Maklerski BOŚ); przykładowe pliki eksportu dosłane później — format i dokładna struktura nagłówków nadal nieznane.

## Outcome

Primary metric: trafność importu per pole na golden secie — ≥ 98% dla formatów znanych, ≥ 90% dla formatu nieznanego (bez ręcznego parsera); baseline mierzony w P1-S2.
Guardrail metric: 0 raportów z liczbą niezgodną z metrykami, 0 raportów z rekomendacją, 0 wykonanych instrukcji z treści pliku.

## User story

Jako inwestor z pozycjami u kilku brokerów chcę wgrać ich eksporty i dostać jeden spójny obraz portfela z opisem koncentracji, ekspozycji walutowej i ryzyka, żeby rozumieć, co faktycznie posiadam, bez ręcznego łączenia arkuszy.

## Acceptance criteria

- AC-1: Given eksport w obsługiwanym formacie, when go wgrywam, then widzę pozycje w schemacie kanonicznym zgodne z plikiem co do ilości, walut i identyfikatorów.
- AC-2: Given eksport w formacie, którego system nie zna, when go wgrywam, then system proponuje mapowanie kolumn, pokazuje je do akceptacji i importuje dopiero po walidacji.
- AC-3: Given plik z nieparsowalnymi liczbami albo sumami niezgodnymi z pozycjami, when go wgrywam, then import nie kończy się po cichu: widzę listę problemów z numerami wierszy.
- AC-4: Given pozycje z ISIN, when import się kończy, then każda pozycja ma rozpoznany instrument (ticker, giełda, typ) albo status „nierozpoznany" lub „niejednoznaczny".
- AC-5: Given portfel po imporcie, when generuję raport, then zawiera alokację, koncentrację, ekspozycję walutową i metryki ryzyka, a każda liczba w tekście zgadza się z metrykami policzonymi w kodzie.
- AC-6: Given dowolny portfel, when generuję raport, then raport nie zawiera rekomendacji kupna, sprzedaży ani zmiany wag i kończy się stopką edukacyjną.
- AC-7: Given plik z komórką zawierającą polecenie dla modelu (np. „zignoruj poprzednie instrukcje"), when go wgrywam, then polecenie nie zostaje wykonane, a komórka jest oznaczona jako podejrzana.
- AC-8: Given wyciąg PDF z pozycjami, when go wgrywam, then pozycje trafiają do tego samego schematu kanonicznego co z CSV i XLSX.
- AC-9: Given eksport z danymi osobowymi (imię i nazwisko, numer rachunku), when treść trafia do modelu, then identyfikatory są wcześniej usunięte lub zamaskowane.

## Out of scope

- Rekomendacje, optymalizacja i rebalancing portfela.
- Historia transakcji, XIRR, podatki — później (DuckDB + text-to-SQL).
- Pobieranie danych bezpośrednio z kont brokerskich (logowanie, API brokerów).
- Interfejs graficzny w P1 samym — CLI i raport w markdown pozostają jedynym interfejsem tego projektu. Od epiku `portfolio-webapp` (`docs/specs/portfolio-webapp/`) funkcje P1 są też dostępne przez web UI tamtego epiku, wywoływane przez `service.py` bez zmian w kodzie P1 — na tej samej zasadzie, na jakiej P5 już reużywa P1 jako bibliotekę.

## Priority

Must. MVP cut line: P1-S1 do P1-S5 (CSV/XLSX, identyfikacja, metryki, raport z guardrailami). P1-S6 (PDF) — Should. Transakcje — Later.

## Slices

| Slice | Wartość dla użytkownika | Czego uczy |
|---|---|---|
| P1-S1 Import jednego formatu + golden set | jeden broker działa end-to-end | schemat kanoniczny, `Decimal`, baseline deterministyczny |
| P1-S2 Nieznany format przez LLM | kolejni brokerzy bez pisania parserów | structured outputs, pętla samokorekty, eval per pole |
| P1-S3 Identyfikacja instrumentów | wiadomo, co to za papier i gdzie notowany | tool use (OpenFIGI), cache |
| P1-S4 Metryki portfela | koncentracja, waluty, ryzyko w liczbach | „kod liczy, model objaśnia" |
| P1-S5 Raport z guardrailami | czytelny opis bez rekomendacji | eval wierności liczb, no-advice, prompt injection |
| P1-S6 Wyciągi PDF | import z wyciągów, nie tylko arkuszy | wejście PDF (document input) |

## Dependencies and risks

- Wymaga `lab-foundation` (klient LLM, rejestr promptów, harness evali).
- Prawdziwe eksporty to dane osobowe: tylko `data/private/`; golden set syntetyczny albo zanonimizowany.
- Historia cen do metryk ryzyka: yfinance, wyłącznie lokalnie (GPW z sufiksem `.WA`). Brak historii = metryka liczona dla części portfela z jawnym pokryciem.
- Klasyfikacja sektorowa: brak darmowego wiarygodnego źródła dla GPW. ASSUMPTION: klasyfikacja przez LLM z evalem albo ręczna mapa — decyzja przed P1-S4.

## Open questions

| # | Question | Owner | Due |
|---|---|---|---|
| 1 | Format i dokładna struktura eksportów XTB i Bossa (CSV/XLSX/PDF, nagłówki) — czeka na przykładowe pliki | Tomasz | przed P1-S1 |
| 2 | Waluta bazowa raportu — PLN? | Tomasz | przed P1-S4 |
| 3 | Klasyfikacja sektorów w MVP: LLM z evalem, ręczna mapa czy pominąć? | Tomasz | przed P1-S4 |
