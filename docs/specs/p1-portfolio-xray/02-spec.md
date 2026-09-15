# p1-portfolio-xray - Specification

Status: Ready for architect
Owner role: BA
Upstream: 01-story.md

## Glossary

| Term | Meaning |
|---|---|
| Eksport | plik od brokera (CSV, XLSX, PDF) z pozycjami na dzień wyceny |
| Sygnatura formatu | znormalizowany zestaw nagłówków + separator + kodowanie, identyfikujący format |
| Konfiguracja parsera | zapisane mapowanie kolumn i reguł formatu na schemat kanoniczny, z wersją |
| Pozycja | posiadany instrument na jednym rachunku u jednego brokera |
| Instrument | papier zidentyfikowany przez ISIN / FIGI, ticker, giełdę i typ |
| Waluta bazowa | waluta, w której liczone są wagi i metryki portfela |
| Waga | udział wartości rynkowej pozycji w wartości portfela, w walucie bazowej |
| Pokrycie | suma wag pozycji, dla których dostępna jest historia cen |
| Pozycja nierozpoznana | instrument bez dopasowania w OpenFIGI |
| Pozycja niejednoznaczna | kilka pasujących notowań bez reguły rozstrzygającej |

## Actors and permissions

| Actor | Action | Allowed |
|---|---|---|
| Właściciel | wgrywa pliki, akceptuje konfigurację nowego formatu, generuje raport | tak |
| Model (LLM) | proponuje konfigurację parsera, pisze narrację raportu | tak — bez danych identyfikujących osoby |
| Model (LLM) | liczy metryki lub przelicza waluty | nie |
| Model (LLM) | wywołuje narzędzie identyfikacji instrumentu (OpenFIGI) | tak — tylko odczyt |

## Functional requirements (EARS)

Import
- REQ-001 (AC-1): When a file whose format signature matches an approved parser configuration is imported, the system shall parse it with that configuration without calling the model.
- REQ-002 (AC-2): When a file's format signature matches no approved configuration, the system shall request a parser configuration from the model that conforms to the configuration schema.
- REQ-003 (AC-2): When the model proposes a configuration, the system shall show the column mapping and the first 5 parsed rows, and store the configuration only after the owner approves it.
- REQ-004 (AC-3): If parsing with a proposed configuration produces validation errors, then the system shall send the errors to the model for a corrected configuration at most 2 times, and then stop with the list of errors.
- REQ-005 (AC-3): If any row fails validation during import, then the system shall report every problem with row number and field, and shall not produce a portfolio.
- REQ-006 (AC-9): Before any file content is sent to the model, the system shall mask values in columns classified as personal identifiers (name, account number, address, PESEL, e-mail).
- REQ-007 (AC-7): The system shall pass file content to the model only inside a delimited data section with an instruction that the section contains data, not instructions.
- REQ-008 (AC-7): If a cell contains text that addresses the model or resembles instructions, then the system shall flag the cell as suspicious in the import report.
- REQ-009 (AC-8): Where the input is a PDF statement, the system shall extract positions into the canonical schema and apply the same validation rules as for tabular files.

Identyfikacja
- REQ-020 (AC-4): When a position has an ISIN, the system shall resolve it through OpenFIGI to FIGI, ticker, exchange code and security type.
- REQ-021 (AC-4): If resolution returns several listings, then the system shall apply the listing selection rule and record which rule decided.
- REQ-022: The system shall cache identification results on disk and reuse them for the same ISIN.

Metryki
- REQ-030 (AC-5): The system shall compute in code: weights, allocation by asset class, currency and account type, HHI, effective number of positions and top-5 share.
- REQ-031 (AC-5): Where daily price history of at least 250 trading days is available, the system shall compute annualized volatility, historical 1-day VaR at 95%, maximum drawdown and beta against the selected benchmark for the covered part of the portfolio.
- REQ-032: If price history is missing for some positions, then the system shall report the coverage and compute risk metrics only for covered positions.
- REQ-033: The system shall convert values to the base currency with NBP table A mid rates from the valuation date, or from the previous business day when that date has no table.

Raport
- REQ-040 (AC-5): When a report is generated, the system shall give the model only the metrics JSON and instrument metadata, never the raw file.
- REQ-041 (AC-5): The system shall check that every number in the report text matches a value in the metrics JSON within rounding tolerance, and shall reject the report otherwise.
- REQ-042 (AC-6): The report shall contain no recommendation to buy, sell or change weights, and shall end with the fixed educational footer.
- REQ-043: The report shall be written in Polish and shall state the valuation date, base currency, data coverage and that risk metrics assume current weights applied to past prices.

## Business rules

Obsługa formatu

| Sygnatura znana | Konfiguracja zatwierdzona | Wynik |
|---|---|---|
| tak | tak | parser bez LLM |
| tak | nie | prośba o akceptację zapisanej propozycji |
| nie | – | propozycja konfiguracji od modelu |

Wybór notowania przy wielu wynikach OpenFIGI

| Notowania w walucie pozycji | Rynek brokera znany | Wynik |
|---|---|---|
| dokładnie jedno | – | to notowanie |
| więcej niż jedno | tak | notowanie z rynku brokera |
| więcej niż jedno | nie | `ambiguous` |
| żadne | – | `unresolved` |

Duplikaty

| Ten sam ISIN | Ten sam rachunek i broker | Wynik |
|---|---|---|
| tak | tak | pozycje zsumowane + ostrzeżenie |
| tak | nie | osobne pozycje |

## Data and validation

Pozycja w schemacie kanonicznym

| Field | Type | Required | Range or format | Validation message |
|---|---|---|---|---|
| `broker` | string | tak | znany broker albo `other` | `Unknown broker '<value>'` |
| `account_type` | enum | tak | `regular` / `ike` / `ikze` / `other` | `Invalid account type in row <n>` |
| `instrument_name` | string | tak | 1–200 znaków | `Missing instrument name in row <n>` |
| `isin` | string | nie | 12 znaków, poprawna suma kontrolna | `Invalid ISIN checksum in row <n>` |
| `symbol` | string | nie | jak u brokera | – |
| `asset_class` | enum | tak | `equity` / `etf` / `bond` / `fund` / `cash` / `crypto` / `derivative` / `other` | `Invalid asset class in row <n>` |
| `quantity` | Decimal | tak | ≠ 0; ujemna tylko dla `derivative` | `Quantity must be non-zero in row <n>` |
| `avg_cost` | Decimal | nie | ≥ 0 | `Negative average cost in row <n>` |
| `cost_currency` | string | gdy `avg_cost` | ISO 4217 | `Unknown currency '<c>' in row <n>` |
| `market_value` | Decimal | nie | ≥ 0 poza `derivative` | `Negative market value in row <n>` |
| `market_currency` | string | gdy `market_value` | ISO 4217 | `Unknown currency '<c>' in row <n>` |
| `valuation_date` | date | tak | nie z przyszłości | `Valuation date in the future` |

Walidacja zbiorcza: jeśli plik podaje wartość portfela, suma `market_value` musi się z nią zgadzać w tolerancji (ASSUMPTION: 0,5%).

Metryki

| Metryka | Definicja |
|---|---|
| Waga | `market_value` w walucie bazowej / suma wartości portfela |
| HHI | suma kwadratów wag |
| Efektywna liczba pozycji | 1 / HHI |
| Udział top-5 | suma pięciu największych wag |
| Zmienność roczna | odchylenie standardowe dziennych log-zwrotów portfela × √252 |
| VaR 95% 1D historyczny | minus 5. percentyl dziennych zwrotów portfela przy obecnych wagach |
| Max drawdown | największy spadek wartości od szczytu przy obecnych wagach |
| Beta | kowariancja zwrotów portfela i benchmarku / wariancja zwrotów benchmarku |

## Edge and error cases

- Liczby: `1 234,56`, `1,234.56`, `1234.56`, spacja niełamliwa, minus `−` (U+2212), ujemne w nawiasach.
- Daty: `DD.MM.RRRR`, `RRRR-MM-DD`; `MM/DD/RRRR` vs `DD/MM/RRRR` niejednoznaczne → pytanie do właściciela.
- Kodowanie: UTF-8, UTF-8 z BOM, Windows-1250; separator `;` albo `,`.
- Wiersze sum i puste, nagłówek w kilku wierszach, scalone komórki XLSX.
- Ułamkowe akcje (Trading212, Revolut), gotówka jako pozycja, pozycje short i CFD (XTB).
- Ta sama spółka na rachunku zwykłym i IKE → dwie pozycje.
- ISIN notowany na kilku giełdach → reguła wyboru notowania.
- Brak tabeli NBP w dniu wyceny (weekend, święto) → poprzedni dzień roboczy; waluta spoza tabeli A → tabela B albo błąd.
- Brak historii cen (debiut, wycofanie z obrotu) → pokrycie poniżej 100%.
- Plik większy niż limit (ASSUMPTION: 5 MB lub 5000 wierszy) → komunikat, bez importu.
- Polecenie dla modelu w nazwie instrumentu albo w komentarzu → komórka oznaczona, polecenie ignorowane.

## Non-functional requirements

- Performance: import znanego formatu < 2 s; nieznanego formatu z pętlą samokorekty < 60 s.
- Koszt (ASSUMPTION): import nieznanego formatu < 0,20 USD; raport < 0,10 USD.
- Security and privacy: prawdziwe pliki tylko w `data/private/`; identyfikatory maskowane przed wysłaniem do API; trace'y lokalnie.
- Audit and logging: import zapisuje wersję użytej konfiguracji parsera; raport — wersję promptu, model i datę kursów NBP.

## Traceability

| AC | REQ |
|---|---|
| AC-1 | REQ-001 |
| AC-2 | REQ-002, REQ-003 |
| AC-3 | REQ-004, REQ-005 |
| AC-4 | REQ-020, REQ-021 |
| AC-5 | REQ-030, REQ-031, REQ-040, REQ-041 |
| AC-6 | REQ-042 |
| AC-7 | REQ-007, REQ-008 |
| AC-8 | REQ-009 |
| AC-9 | REQ-006 |

## Open questions

| # | Question | Owner |
|---|---|---|
| 1 | Waluta bazowa — PLN? | Tomasz |
| 2 | Benchmark do bety: WIG, ETF na MSCI ACWI czy wybór użytkownika? | Tomasz |
| 3 | Tolerancja zgodności sumy z wartością portfela z pliku — 0,5%? | Tomasz |
| 4 | Limit rozmiaru pliku? | Tomasz |
| 5 | Klasyfikacja sektorów w MVP? | Tomasz |
