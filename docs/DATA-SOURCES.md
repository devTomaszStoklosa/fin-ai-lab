# Źródła danych

Werdykty licencyjne dla źródeł wspólnych z Analizoteką pochodzą z jej planu danych (`C:\Users\Tomasz\Desktop\Repo\InvestorSocial\DATA-SOURCES-PLAN.md`, zweryfikowane na żywo 2026-07-31). Przed użyciem produkcyjnym sprawdź je ponownie.

## Zasady

1. **Nauka ≠ produkt.** Kolumna „Nauka" mówi, czy wolno użyć lokalnie w tym repo. Kolumna „Produkt" — czy wynik może trafić do Analizoteki lub być publikowany.
2. **Throttling po naszej stronie**, nie przez odpowiedzi 429. Każdy klient w `core.http` ma minimalny odstęp między żądaniami.
3. **Cache na dysku** (`data/cache/`) — tych samych danych nie pobieramy dwa razy.
4. **Atrybucja** idzie razem z danymi (źródło + URL w metadanych).
5. **Żadnego scrapowania** stron chronionych antybotem ani treści za paywallem.
6. **Dane osobowe** (eksporty z brokerów): tylko `data/private/`; przed wysłaniem do API usuń imiona, numery rachunków i inne identyfikatory.

## Źródła

| Źródło | Co daje | Klucz | Limit | Nauka | Produkt | Projekty |
|---|---|---|---|---|---|---|
| SEC EDGAR (`data.sec.gov`, `sec.gov/Archives`) | listy zgłoszeń, 10-K/10-Q/8-K, XBRL `companyfacts`, `frames`, mapa `company_tickers.json` | nie, ale **wymagany `User-Agent` z kontaktem** (bez niego 403) | 10 req/s | tak | tak (domena publiczna USA) | P2, P5 |
| FRED (`api.stlouisfed.org`) | makro USA, rentowności, stopy | **tak** (darmowy) | 120 req/min | tak | **per seria** — patrz niżej | P3 |
| NBP (`api.nbp.pl`) | kursy walut (tabele A/B/C), złoto | nie | brak (zachowaj umiar) | tak | tak | P1, P3 |
| GUS BDL (`bdl.stat.gov.pl`) | statystyki PL | opcjonalny | 5/s anonimowo, 10/s z kluczem | tak | tak, **CC BY 4.0** (atrybucja) | P3 |
| GDELT (feed plików) | artykuły, ton medialny | nie | brak | tak | tak (jawnie dozwolone) | P3, P4 |
| GDELT DOC 2.0 API | wyszukiwanie artykułów | nie | **1 req / 5 s, ryzyko bana IP** | tylko ad-hoc | nie w automatach | P3 |
| RSS Bankier (`bankier.pl/rss/wiadomosci.xml`, `/gielda.xml`) | nagłówki i leady newsów PL | nie | brak | tak, lokalny korpus | tylko tytuł ≤ 120 i streszczenie ≤ 150 znaków (art. 15 DSM) | P3, P4 |
| RSS Strefa Inwestorów (`strefainwestorow.pl/rss.xml`) | newsy PL; `description` ≈ cały artykuł | nie | brak | tak, lokalny korpus | jak wyżej — przycinanie krytyczne | P3, P4 |
| OpenFIGI | ISIN → FIGI, ticker, giełda, typ instrumentu | opcjonalny (wyższe limity) | zależny od klucza — sprawdź dokumentację | tak | sprawdź warunki | P1 |
| yfinance (Yahoo) | historyczne ceny; GPW z sufiksem `.WA` | nie | nieoficjalne, bywa blokowane | **tylko lokalnie** | **nie** | P1, P3, P5 |
| KRS / eKRS | roczne sprawozdania finansowe spółek PL (z opóźnieniem) | nie | brak | tak | tak (informacja publiczna) | P2 (opcjonalnie) |
| Raporty okresowe spółek GPW (PDF z relacji inwestorskich) | sprawozdania PL | nie | pobieranie ręczne, kilka plików | tak | sprawdź licencję | P2 |
| FinanceBench (Patronus AI) | otwarta próbka ok. 150 pytań do raportów spółek US | nie | — | tak | sprawdź licencję | P2 |
| FinancialPhraseBank | zdania finansowe EN z sentymentem | nie | — | tak | **nie** (CC BY-NC-SA 3.0) | P4 |
| FiQA | sentyment i QA finansowe EN | nie | — | tak | sprawdź licencję | P4 |
| Checkpointy HerBERT / Bielik | modele bazowe do fine-tuningu | nie | — | tak | licencja zależy od checkpointu — czytaj model card | P4 |

### FRED — licencja per seria

Serie Fed, BLS i BEA są domeną publiczną (np. `DGS10`, `DGS2`, `T10Y2Y`, `DFF`, `CPIAUCSL`, `UNRATE`). Serie podmiotów trzecich (S&P, ICE BofA, Moody's, CBOE — np. `VIXCLS`) nie nadają się do redystrybucji: tylko nauka. Informacja o prawach siedzi w polu `notes` serii, więc repo trzyma ręcznie zweryfikowaną allowlistę serii, a nie przyjmuje dowolnych ID.

### SEC — pułapki danych

- `companyfacts` dużej spółki ma 10–20 MB — pobieraj na żądanie, z cache.
- Ta sama pozycja występuje pod różnymi tagami (`Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet`) zależnie od roku i spółki. Potrzebna mapa „grupa tagów → jedno pojęcie" z priorytetem; bez niej szereg przychodów urywa się przy zmianie standardu (ASC 606, 2018).
- Ten sam okres pojawia się w kilku zgłoszeniach; obowiązuje obserwacja z najnowszą datą złożenia.
- Ta sama wartość bywa raportowana w kilku jednostkach — filtruj po jednostce.

### GDELT i sentyment PL

Ton dla polskich artykułów GDELT liczy na tłumaczeniu maszynowym, więc sygnał jest zaszumiony. To jest motywacja projektu P4, nie gotowy „nastrój rynku".

## Wykluczone

| Źródło | Powód |
|---|---|
| Google News RSS | jawny zakaz użycia poza osobistym czytnikiem |
| PAP Biznes | ochrona Imperva + licencjonowana treść |
| Dane rynkowe i komunikaty GPW | wymagają płatnej licencji na dane rynkowe |
| ESPI/EBI przez Bankier | dane dostarcza Notoria — cudza licencja; feed `komunikaty.xml` jest martwy |

## Nowe źródło — checklista

1. Warunki użycia: nauka / produkt, atrybucja, zakaz redystrybucji.
2. Limity i wymagane nagłówki.
3. Wpis w tabeli powyżej (przez commit, z datą weryfikacji).
4. Klient w `core.http` z throttlingiem i cache.
5. Test bez sieci na nagranej odpowiedzi.
