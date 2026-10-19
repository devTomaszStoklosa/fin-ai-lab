# portfolio-webapp - Specification

Status: Ready for architect
Owner role: BA
Upstream: 01-story.md

## Glossary

| Term | Meaning |
|---|---|
| Snapshot | stan pozycji danego portfela w jednym punkcie w czasie, powstały z importu pliku brokera, który sam już opisuje bieżący stan (np. XTB) |
| Transakcja | pojedyncza operacja kupna/sprzedaży z eksportu typu historia operacji (np. Bossa); nie jest pozycją |
| Ledger | pełny, deduplikowany zbiór transakcji danego portfela, z którego pozycje są liczone przez replay |
| Replay | przeliczenie bieżących pozycji od zera z całego ledgera; nigdy merge dwóch wcześniej policzonych stanów |
| Klucz deduplikacji | hash wszystkich kolumn wiersza transakcji, używany do wykrycia, że dany wiersz już jest w ledgerze |
| Portfel | zbiór pozycji jednego właściciela, niezależny od tego, z ilu plików/brokerów pochodzą |
| Agregat | nazwany przez właściciela zbiór instrumentów i/lub innych agregatów, do prezentacji łącznej ekspozycji niezależnej od tego, przez jaki instrument jest trzymana |
| Cykl agregatów | sytuacja, w której agregat pośrednio zawierałby sam siebie — zabroniona, odrzucana przy zapisie |
| Lot | pojedynczy zakup składający się na pozycję, z datą otwarcia (XTB: wiersz szczegółowy pod wierszem pozycji w „Open Positions”) |
| Kotwica wyceny | znana wartość jednej sztuki w znanym dniu — wartość z ostatniego importu, który trzymał instrument; inne dni to kotwica przesunięta o stosunek kursów |
| Wycena bieżąca | wartość liczona z notowań pobranych przy wejściu na ekran, nie z wartości zapisanej przy imporcie |
| Podział | nazwane drzewo grup właściciela, w którym każde aktywo jest w co najwyżej jednej grupie — do udziałów sumujących się do 100%; w kodzie `breakdown` (nie `split`, żeby nie mylić ze splitem akcji) |
| Podział wbudowany | podział liczony z danych, bez konfiguracji: aktywa, klasa aktywów, waluta notowań, portfel |
| Aktywo | to, co właściciel posiada niezależnie od brokera — jeden lub więcej instrumentów brokerów połączonych w jedno; w kodzie klucz aktywa (`asset key`): ISIN, gdy ma go którykolwiek z połączonych instrumentów |
| Łączenie instrumentów | uznanie dwóch instrumentów z różnych kont/brokerów za jedno aktywo: automatycznie przy tym samym FIGI, w pozostałych przypadkach decyzją właściciela |
| Udział w grupie / w portfelu | wartość elementu podzielona przez wartość jego grupy / przez wartość całego zakresu (portfel albo wszystkie portfele) |
| Zwrot ważony czasem (time-weighted) | zwrot portfela liczony dzień po dniu jako (wartość wczorajszego składu po dzisiejszych cenach + dywidendy wpłacone dziś) / wartość wczorajsza, a potem mnożony przez kolejne dni — wpłaty, wypłaty, zakupy i sprzedaże go nie zmieniają, więc da się go porównać z indeksem (S14, #273) |
| Benchmark | szereg, z którym porównuje się zwrot portfela: indeks z dywidendami, fundusz, który je reinwestuje, albo kurs skorygowany o dywidendy, przeliczony na PLN kursem NBP z każdego dnia |
| Wypłata dywidendy | to, co jedna dywidenda wniosła na konto: w XTB wiersz „Dividend” razem z wierszami „Withholding tax” tego samego dnia i instrumentu, w Bossie jeden wiersz „Wypłata/Korekta dywidendy”; kwota po podatku pobranym przez brokera, bez własnego liczenia podatku (#267) |

## Actors and permissions

| Actor | Action | Allowed |
|---|---|---|
| Właściciel | wgrywa pliki, dodaje/edytuje/usuwa pozycje ręczne, akceptuje nową konfigurację parsera, generuje raport | tak |
| Właściciel | edytuje pozycję pochodzącą z importu pliku | nie — tylko przez ponowny import |
| Właściciel | tworzy, edytuje i usuwa agregaty | tak |
| P1 (`service.py`, `report/orchestrator.py`) | parsuje pliki, liczy metryki, generuje raport | tak, bez zmian w jego kodzie |
| Sieć spoza localhost | dowolne zapytanie do API | nie — serwer nasłuchuje tylko na localhost |

## Functional requirements (EARS)

Import (reużycie P1)
- REQ-001 (AC-1): When a file is uploaded for a broker with an approved parser configuration in P1's registry, the system shall import it by calling `portfolio_xray.service.import_file` unchanged, not by reimplementing parsing.
- REQ-002 (AC-1): When a file's format signature matches no approved configuration, the system shall offer the same propose/approve flow P1's CLI uses (`on_new_config_proposed`), adapted to two HTTP calls (propose, then approve or reject) instead of a terminal prompt.
- REQ-003: When a CSV is uploaded for Bossa, the system shall import it through P1's ledger-aggregation capability (`ledger.py`), never through the row-mapping/propose-approve path meant for position-snapshot brokers; there is no propose/approve step, since Bossa has exactly one known export shape.
- REQ-004 (AC-6): The system shall pass through every warning P1's import returns (including suspicious-cell flags from `privacy/injection.py`) to the response body unchanged; it shall not filter or summarize them away.

Ręczne pozycje
- REQ-010 (AC-4): When the owner submits a manual position, the system shall validate it against the same canonical `Position` model P1 uses for imported positions, with `broker` set to a fixed value identifying it as manual.
- REQ-011: The system shall allow editing and deleting a manually entered position; it shall not allow editing a position that came from a file import — only a new import can change it.

Trwałość i historia
- REQ-020 (AC-5): When a file is imported for a broker whose export already represents current holdings (e.g. XTB), the system shall store the result as a new, independent snapshot; it shall never merge it with a previous snapshot's positions.
- REQ-021: When transactions are imported for a broker whose export is a transaction ledger (e.g. Bossa, once its P1 capability exists), the system shall store each transaction keyed by a deduplication hash of its full row and shall ignore any row whose hash is already stored; positions for that broker shall always be computed by replaying the complete transaction table, never by merging previously computed positions.
- REQ-022: When a file is imported, the system shall record and return the minimum and maximum date found in the file, so the owner can check for gaps against previously imported files.
- REQ-023: The system shall persist all portfolio data (snapshots, transactions, positions, cached reports) in a DuckDB file under `data/private/`; no persisted file containing real portfolio data shall be tracked by git.

Metryki i wyświetlanie
- REQ-030 (AC-2): When a snapshot's metrics are requested, the system shall compute them by calling P1's existing metrics functions (`metrics/weights.py`, `metrics/risk.py`, `metrics/fx.py`), never by reimplementing the computation.

Raport
- REQ-040 (AC-3): When the owner requests a report for a snapshot, the system shall call P1's `report/orchestrator.py::generate_report` unchanged and persist the resulting text with its cost, model and generation timestamp.
- REQ-041 (AC-3): When a cached report already exists for the current snapshot, the system shall return it instead of generating a new one, unless the owner explicitly requests regeneration.
- REQ-042 (AC-3): The system shall show a persistent, always-visible disclaimer stating the report is descriptive, not investment advice, independent of the report text's own educational footer.

Sieć i dostęp
- REQ-050 (AC-7): The system shall bind its HTTP server to `localhost` only, with no authentication layer, by default.

Agregaty
- REQ-060 (AC-8): When the owner creates an aggregator with a name and a set of members (instruments and/or other aggregators), the system shall persist it and compute its value as the sum of its members' market values converted to the base currency.
- REQ-061 (AC-9): When an aggregator's value is computed, the system shall collect the set of unique instruments reachable across its full transitive membership and sum each one once, so an instrument reachable through more than one path is never counted twice.
- REQ-062 (AC-10): When the owner adds a member to an aggregator, the system shall reject the change if the proposed member is, directly or through nested aggregators, the target aggregator itself.
- REQ-063: The system shall allow an instrument or an aggregator to belong to more than one aggregator at the same time.
- REQ-064: The system shall allow renaming an aggregator and changing its membership, and shall allow deleting an aggregator; deleting an aggregator that is itself a member of another aggregator shall also remove that membership, leaving no dangling reference.
- REQ-065: The system shall identify an aggregator's instrument members by a stable key — the ISIN when the instrument has one, otherwise broker and symbol together — never by a position row's per-snapshot id, so membership survives a re-import.

Widok zbiorczy i dzienna historia wartości (S10)
- REQ-070 (AC-11): When the start page is opened, the system shall value every portfolio at current quotes and show their sum in PLN, each portfolio's value and share of that sum, and one table of every current position across all portfolios.
- REQ-071 (AC-12): When a value history is requested, the system shall return one value per calendar day from the earliest known holding date to today, computed as the quantity held that day times that day's unit value; weekends and holidays reuse the last close and the last NBP rate on or before the day.
- REQ-072 (AC-12): The system shall compute a unit's value on day d as the latest import's stored value per unit (the anchor) times close(d)/close(anchor date), and — when the instrument's quote currency differs from the currency the broker recorded — times the NBP rate ratio of the quote currency over the recorded currency; it shall never treat a foreign absolute price as if it were in the account's currency (issue #188).
- REQ-073 (AC-12, AC-14): The system shall derive the quantity held on day d from: the latest import dated on or before d; plus lots a later import dates between that import and d; capped at the larger of the two imports around d. For a ledger broker (Bossa) it shall use the running sum of transactions instead. A manual position shall count from its entry date at its own value, never re-priced from market data.
- REQ-074 (AC-14): When an XTB export is imported, the system shall store the open date of each long lot from the Open Positions detail rows, but only for a position whose lots add up exactly to its quantity; a lot with an unreadable date drops lot detail for that position, never the import.
- REQ-075 (AC-13): The system shall show for each current position its quantity, purchase price, current price and return in the currency the broker recorded (the same one the purchase price is in), and its value in PLN.
- REQ-076: When a quote or an NBP series cannot be fetched, the system shall keep the instrument at its anchor value (or leave out the FX factor) and list a readable warning with the instrument's name; it shall never fail the whole view.
- REQ-077: The system shall mark every day on which a held quantity changes, so a jump caused by a purchase or sale is not read as a price move, and shall state on screen that the change of value includes purchases and sales and is not a rate of return.

Udziały i podziały (S11)
- REQ-080 (AC-16): The system shall let the owner create, rename, duplicate and delete any number of breakdowns, and mark at most one of them as the default shown first.
- REQ-081 (AC-16): The system shall store at most one group per (breakdown, instrument key) pair, enforced by the database's primary key, so within one breakdown shares always add up to 100%; the same instrument may belong to a different group in each breakdown.
- REQ-082 (AC-18): When a group is created or moved, the system shall reject a parent that is the group itself, one of its descendants, or a group of another breakdown.
- REQ-083: When a group is deleted, the system shall move its subgroups and its assigned instruments to the deleted group's parent (to "Bez grupy" at the top level), never delete them silently.
- REQ-084 (AC-15, AC-17): When shares are requested for a breakdown and a scope (one portfolio or all), the system shall value the scope's current positions exactly as the valuation view does (REQ-072), sum them per instrument key, and return the breakdown's full tree with each node's value, share of its parent and share of the whole scope, computed in Decimal by the backend; instruments not assigned to any group form a "Bez grupy" node.
- REQ-085 (AC-19): The system shall offer built-in breakdowns computed from the data itself: per asset, per asset class, per quote currency (the currency the broker recorded when the quote currency is unknown) and, in the all-portfolios scope, per portfolio.
- REQ-086: The system shall key assignments by the same stable instrument key as aggregators (REQ-065) — manual positions by their own id — so an assignment survives a re-import; an assignment to an instrument no longer held is kept and simply contributes nothing.
- REQ-087 (AC-15): The chart shall show at most six slices per level (the rest folded into "Pozostałe"), a bar instead of a circle for a level of one or two elements, and a table with every value, so no share is readable only from colour or angle.

Jedno aktywo u wielu brokerów (S12)
- REQ-090 (AC-20): When two held instruments resolved to the same FIGI at import, the system shall treat them as one asset, unless the owner answered that they differ.
- REQ-091 (AC-21, AC-22): When the owner answers for a pair of instruments, the system shall store the answer ("the same" or "different") per pair and apply it to every portfolio and view; joining is transitive, and the asset is keyed by an ISIN of any of its instruments, else by the key of an imported one.
- REQ-092 (AC-21): The system shall suggest, never join by itself, pairs of instruments from different brokers that share a ticker (OpenFIGI's ticker or the broker's own symbol without its market suffix) or a name (ignoring legal form, diacritics and spacing), where both have a known value per unit today: dropped above 25% difference, and for a name-only match above 10%; answered pairs, joined pairs and manual positions are never suggested.
- REQ-093 (AC-20): The all-portfolios table shall show one row per asset, summing quantity and value across its positions and averaging purchase and current price weighted by quantity only where every position states them in the same currency; the row expands to each portfolio's own position. Shares and breakdowns (REQ-084) shall use the asset key, the asset's name and — where one of its instruments knows it — its asset class and quote currency.
- REQ-094 (AC-22): When the owner detaches an instrument from an asset, the system shall record it as different from each other member and keep the remaining members joined.
- REQ-095: An assignment stored under an instrument's own key shall count for its asset when the asset has none of its own; assigning an asset stores it under the asset key and removes its members' own assignments in that breakdown.

Dywidendy — historia (S13, #265)
- REQ-100 (AC-23): When an XTB export is imported, the system shall store each cash operation's `Ticker` and `Comment` (both optional in the file); when a re-import lists an operation already stored without them, it shall fill them in and never store the operation twice.
- REQ-101 (AC-23): The system shall join an XTB dividend row and the withholding-tax rows booked on the same day for the same instrument (and the same correction flag) into one payment whose amount is what was credited; it shall not compute any tax itself.
- REQ-102 (AC-23, AC-25): The system shall link a payment to an instrument: XTB by its ticker (key `xtb:<ticker>`), Bossa by the company the title names, matched without regard to case against the portfolio's trade names or the OpenFIGI tickers of its positions; an unmatched payment keeps the name from its title and still counts.
- REQ-103 (AC-24): The system shall convert each payment at the NBP mid rate of its own day (the last one on or before it) — the investment result's rule, so the history's total equals its `dividends`; a payment in a currency without an NBP series shall be listed but left out of the sums, with a warning.
- REQ-104 (AC-23): For one portfolio or all of them, the system shall return the totals (all time, current calendar year, last 365 days), every year from the first payment to the current one with its twelve monthly amounts, one row per asset (S12 asset key) with payment count, last payment date, total and last-12-months, and every payment newest first.

Dywidendy — szacunek (S13, #266)
- REQ-105 (AC-26): For each instrument held today (the latest import's positions plus manual ones), the system shall repeat every per-share dividend dated in the last 365 days in the same month of the next calendar year, times today's quantity, at today's NBP mid rate; amounts are gross — no tax is applied (#267).
- REQ-106 (AC-27): The system shall take the per-share amounts from Yahoo when it has closes for the instrument's ticker (pence converted to pounds), otherwise from the per-share amounts XTB states in this account's dividend comments, otherwise list the instrument as without data.
- REQ-107 (AC-27): When both Yahoo and the XTB statements give payouts in the window and their average payout, in PLN at today's rate, differs by more than 25%, the system shall flag the instrument and name it in a warning; the estimate stays Yahoo's.
- REQ-108 (AC-26): The system shall state the yield as the last 12 months' Yahoo payouts per share over the latest close, both in the listing's quote unit; it shall serve the estimate from endpoints separate from the history, and a failed Yahoo lookup shall degrade to "no data" for that instrument, never fail the whole estimate.

Dywidendy — podatek w szacunku (S13, #267)
- REQ-109 (AC-28): For each holding the system shall derive the share withheld before payout and the share still due in the Polish tax return from the portfolio's account type and the issuer's country: IKE/IKZE — a Polish issuer 0%, a foreign one its withholding at source with nothing due; regular — a Polish issuer 19% withheld by the broker, a foreign one its withholding at source plus, when that is below 19%, the difference due in the return; any other account type — unknown.
- REQ-110 (AC-28): The system shall take a foreign issuer's withholding rate from the account's own latest statement for that instrument (XTB "WHT x%", Bossa "netto x%" or "brutto"), else from the rates seen in the owner's statements per country, else treat it as unknown: the amount reaching the account then equals the gross one and the instrument is named in a warning.
- REQ-111 (AC-28): The system shall read the issuer's country from the ISIN, else from the country of XTB's exchange suffix; it shall show what reaches the account by month and in total, the top-up as a separate total never subtracted from it, and a combined asset's rate only when all its holdings share it.

Porównanie z benchmarkiem (S14, #273)
- REQ-120 (AC-29): For each portfolio and every day of its value history, the system shall return the value of the previous day's holdings at that day's prices and the dividends credited that day (net of withholding tax, in PLN at the NBP mid rate of their own day, REQ-103's rule), and for all portfolios together a return index: 1 on the first day, then multiplied each day by (previous holdings at today's prices + dividends) / previous day's value; a day after one without any value keeps the index unchanged.
- REQ-121 (AC-30): The system shall flag a portfolio whose imports carry no dividends (no cash operations) so the page can state that its return leaves them out.
- REQ-122 (AC-29): The system shall offer built-in benchmarks whose series include dividends — WIG20 and mWIG40 through the Beta ETF total-return funds (Yahoo has no history of the GPW indices themselves), S&P 500 Total Return, Nasdaq-100 through QQQ's dividend-adjusted closes, DAX, MSCI World through an accumulating fund, gold — and accept any Yahoo ticker (letters, digits and `. ^ = -`, up to 20 characters), always reading dividend-adjusted closes.
- REQ-123 (AC-29, AC-30): For a benchmark the system shall return, on the valuation's day axis, its value in PLN as an index equal to 1 on its first day with a price (close ratio times the NBP rate ratio, weekends and holidays at the last close); an unknown ticker, a failed Yahoo lookup and a currency without an NBP series shall each be a distinct, readable error, never a failure of the valuation.
- REQ-124 (AC-29): The page shall show the comparison as a third mode of the value chart, with the chart's range and day under the cursor: both returns rebased to 0% on the range's first day, the difference in percentage points, the benchmark fetched only while this mode is open, and the choice remembered in the browser; with some portfolios hidden, the return of the visible ones shall be chained from their own series (REQ-120).
- REQ-125 (AC-31): For each portfolio the system shall return its deposits minus withdrawals in PLN at the NBP mid rate of their own day, per chart day and summed before the chart's first day; together they equal the investment result's `net_deposits`.
- REQ-126 (AC-31): Where every visible portfolio states its deposits, the comparison shall lead with the investment result against the same deposits put into the benchmark: each deposit buys the benchmark at its day's PLN price, each withdrawal sells it, a deposit before the benchmark's first price (or the chart's first day) buys at that first price; the result is today's value of the units minus the deposits.
- REQ-127 (AC-32): For each portfolio the system shall return the value held without daily quotes per day and the gain the return can see (price moves of the holdings plus dividends over the chart); the page shall show that gain against the investment result, as a warning when it misses more than 10% of it (and at least 100 PLN), and the share of value without daily quotes in the range.

Notowania każdego instrumentu (#277)
- REQ-128 (AC-33): On a Bossa import the system shall look up every ISIN the stored ledger traded, held or sold, that has no stored listing yet — once per ISIN for all portfolios, ten ISINs per OpenFIGI request — and store the listing chosen in the currency of the ISIN's latest trade: a PLN trade takes the GPW listing; a USD trade takes the LSE listing for an ETP and the US composite listing otherwise; a single listing on an exchange Yahoo knows is taken as it is. An ISIN without a choice in a currency other than USD shall be looked up again in USD; one still without a choice shall be stored as unresolved. A failed lookup shall store nothing and add an import warning, so the next import asks again.
- REQ-129 (AC-33): The value history shall price a ledger instrument without a ticker of its own by its stored listing, in the listing's quote currency from Yahoo where its anchor states none; a position's own ticker always wins.

Notowania uzupełnione przez właściciela (#285)
- REQ-130 (AC-34): The Instruments screen shall list every held instrument other than a manual position that the valuation priced without daily closes or without a quote currency, naming what is missing, and every instrument with an owner entry; there the owner can enter the instrument's Yahoo symbol, its quote currency (PLN, USD, EUR, GBP or GBp for pence), or both, and clear the entry by leaving both empty. The entry is stored per instrument key, once for every portfolio.
- REQ-131 (AC-34): Before storing a symbol the system shall check that Yahoo has closes for it in the last 31 days: an unknown symbol is refused with a readable error and nothing is stored, and a failed Yahoo lookup is a distinct error. A symbol stored without a currency shall take the currency Yahoo states for it, when it states one.
- REQ-132 (AC-34): From the moment an entry is saved, without a re-import, the value history shall price the instrument by the entry's symbol and move it with the entry's quote currency, over the position's own ticker, a stored listing (REQ-129) and a currency read from an XTB symbol or lot; a manual position is never priced this way. The metrics endpoint, the AI report and the dividend estimate do not use the entry.

Aktywa nienotowane i wyceny właściciela (#288)
- REQ-133 (AC-35): A manual position shall carry a purchase date, given by the owner on adding and on editing it — today when omitted on adding, unchanged when omitted on editing — and stored as its `valuation_date`; a date in the future shall be refused with a readable error. The value history (REQ-073) and the investment result shall date the position and its cost on that day.
- REQ-134 (AC-36): The owner can record and delete valuations of a manual position: a day and a value per unit in PLN, one per day — a later one on the same day replaces it. A valuation dated before the purchase date or in the future shall be refused with a readable error, and so shall moving the purchase date past the earliest valuation.
- REQ-135 (AC-36): A manual position's stored value shall be its quantity times its latest valuation, or times its purchase price without one, kept up to date on every change of the position or of its valuations, so the metrics, aggregators, shares and the AI report use the current value without knowing about valuations; editing a position no longer sets a value itself.
- REQ-136 (AC-36): The value history shall value a manual position at its purchase price from its purchase date and at each valuation from that valuation's day on, as a step — never interpolated between two valuations; it stays a value without daily quotes (REQ-127). The positions table shall show the day of the latest valuation.
- REQ-137 (AC-36): Removing a manual position or its portfolio shall remove its valuations. A manual position whose value was set by hand before #288 shall get that value as one valuation on its entry day, so its history doesn't change.

## Business rules

Wybór ścieżki importu wg brokera

| Broker | Kształt eksportu | Ścieżka |
|---|---|---|
| XTB | stan bieżący (pozycje) | P1's `import_file`, znany format → snapshot |
| inny, nieznany dotąd broker o kształcie pozycji | stan bieżący (pozycje) | P1's propose/approve przez API |
| Bossa | historia transakcji | P1's `ledger.py`, replay całego ledgera → snapshot (REQ-003, REQ-021) |

Edycja pozycji

| Pochodzenie pozycji | Edycja | Usunięcie |
|---|---|---|
| ręczna | tak | tak |
| z importu pliku | nie | nie — tylko nowy import zmienia stan |

Cache raportu

| Raport dla bieżącego snapshotu istnieje | Właściciel prosi o regenerację | Wynik |
|---|---|---|
| nie | – | generuj, zapisz |
| tak | nie | zwróć zapisany |
| tak | tak | generuj ponownie, nadpisz |

Cykle w agregatach

| Proponowany nowy członek już (pośrednio) zawiera agregat docelowy | Wynik |
|---|---|
| tak | odrzucone, czytelny komunikat |
| nie | dodane |

## Data and validation

Snapshot

| Field | Type | Required | Uwagi |
|---|---|---|---|
| `id` | uuid | tak | |
| `portfolio_id` | uuid | tak | |
| `broker` | string | tak | jak w P1's `canonical.Position.broker` |
| `valuation_date` | date | tak | jak w P1's `canonical.Position.valuation_date` |
| `imported_at` | timestamp | tak | |
| `source_file_date_min` / `source_file_date_max` | date | nie | REQ-022, tylko dla importów z pliku |

Transaction (tylko brokerzy typu ledger)

| Field | Type | Required | Uwagi |
|---|---|---|---|
| `dedup_hash` | string | tak, unikalny w ramach portfela | hash pełnego wiersza (REQ-021) |
| `portfolio_id` | uuid | tak | |
| `broker` | string | tak | |
| `executed_at` | timestamp | tak | |
| `isin` | string | tak | poprawna suma kontrolna, jak w P1 |
| `side` | enum | tak | `buy` / `sell` |
| `quantity` | Decimal | tak | > 0 (kierunek niesie `side`, nie znak) |
| `price` | Decimal | tak | > 0 |
| `commission` | Decimal | tak | ≥ 0 |
| `currency` | string | tak | ISO 4217 |

Position (Bossa, wyliczona przez replay) dziedziczy walidację P1's `canonical.Position` bez zmian — replay jedynie produkuje dane wejściowe do tego samego modelu, nie nowy schemat.

Aggregator

| Field | Type | Required | Uwagi |
|---|---|---|---|
| `id` | uuid | tak | |
| `portfolio_id` | uuid | tak | agregaty są per portfel, nie globalne |
| `name` | string | tak | 1–100 znaków |
| `member_instrument_keys` | list[string] | nie | REQ-065 — ISIN albo `broker:symbol`, nie id pozycji |
| `member_aggregator_ids` | list[uuid] | nie | zagnieżdżone agregaty; walidacja cyklu przy zapisie (REQ-062) |

Instrument decision (S12, `instrument_decisions`)

| Field | Type | Required | Uwagi |
|---|---|---|---|
| `key_a`, `key_b` | string | tak | klucze instrumentów (REQ-065, ręczne: `manual:{id}`), `key_a < key_b`; para jest kluczem głównym — nowa odpowiedź zastępuje starą |
| `same` | bool | tak | „to ten sam” / „to różne” (REQ-091) |
| `decided_at` | timestamp | tak | |

Manual valuation (#288, `manual_valuations`)

| Field | Type | Required | Uwagi |
|---|---|---|---|
| `position_id` | uuid | tak | ręczna pozycja |
| `valued_on` | date | tak | nie przed datą zakupu (`valuation_date` pozycji), nie w przyszłości; z `position_id` klucz główny — jedna wycena na dzień (REQ-134) |
| `unit_value` | Decimal | tak | ≥ 0, za sztukę, w PLN |
| `recorded_at` | timestamp | tak | |

Agregaty (S9) zostają per portfel na kluczach instrumentów — w jednym portfelu jest jeden broker, więc łączenie ich nie dotyczy.

## Edge and error cases

S14:
- Dywidenda liczy się w dniu wpłaty na konto, a kurs spada już w dniu ustalenia prawa (zwykle 1–4 tygodnie wcześniej) → przez ten czas zwrot portfela jest chwilowo zaniżony; w dłuższym zakresie się wyrównuje.
- Dywidendy portfela są po podatku u źródła, a indeksy i fundusze z dywidendami liczą je przed podatkiem → porównanie jest lekko na niekorzyść portfela; opisane w przypisie.
- Portfel bez operacji gotówkowych → zwrot bez dywidend, uwaga z nazwą portfela (REQ-121).
- Benchmark z historią krótszą niż zakres (np. fundusz ETF od 2021) → linia zaczyna się od pierwszego notowania, z uwagą od kiedy.
- Pozycja ręczna bez wycen i pozycja bez notowań mają stałą wartość → dzień po dniu 0%, co rozcieńcza zwrot portfela; wycena ręcznej pozycji (#288) wchodzi do zwrotu w całości w dniu wyceny.
- Wszystko sprzedane, a dywidenda wpływa później (wartość z dnia poprzedniego = 0) → ten dzień nie zmienia zwrotu.
- Instrument bez dziennych notowań (od #277 tylko taki, dla którego nie ma notowania w OpenFIGI albo w Yahoo) → stała wartość, jego zysk nie pojawia się w zwrocie w %; porównanie wpłat (REQ-126) tego nie dotyczy, bo liczy się z wyniku inwestycji. Ostrzeżenie (REQ-127) mówi, ile zysku wykres pomija.
- Zwrot w % waży każdy dzień jednakowo: okres z kilkuset złotymi w portfelu liczy się tak samo jak okres z setkami tysięcy — dlatego pierwszą liczbą jest porównanie wpłat, ważone kwotą.

#288:
- Wycena z dnia zakupu → od tego dnia zastępuje cenę zakupu, więc wykres nigdy nie pokazuje ceny zakupu; zwrot w tabeli dalej liczy się od ceny zakupu.
- Zmiana ilości po wycenach → wycena jest za sztukę, więc wartość zmienia się proporcjonalnie; dokupienie po innej cenie to nowa pozycja, nie zmiana ilości.
- Aktywo w innej walucie niż PLN (np. moneta kupiona w EUR) → poza zakresem; ręczne pozycje są tylko w PLN.

#277:
- Instrument zagraniczny kupiony w PLN poza GPW (Moderna, ETF-y z Irlandii) → jedyna linia w PLN to notowanie, którego Yahoo nie zna („MRNAPLN”) → drugie zapytanie w USD; wartość porusza się też z kursem USD/PLN.
- ETF UCITS w USD → linia na LSE, nie linia pozagiełdowa w USA (np. VUAA → VGFPF) z nieaktualnymi kursami.
- Brak notowania w OpenFIGI (GRENEVIA-FIX) albo danych w Yahoo (fundusze Beta TR, ETN Virtune) → stała wartość z ostrzeżeniem, jak dotąd.
- OpenFIGI niedostępne przy imporcie → transakcje zapisane, ostrzeżenie w imporcie, następny import pyta ponownie.
- Wykres liczy z cen zamknięcia i bez prowizji, a wynik inwestycji z cen transakcji po prowizji → zysk widoczny na wykresie może przekroczyć wynik (na danych właściciela w IKE o kilkanaście procent, w około połowie przez prowizje).

S13:
- Wypłaty XTB zapisane przed #265 (bez tickera) → nieprzypisane, pod nazwą instrumentu, dopóki właściciel nie wgra tego eksportu ponownie (REQ-100); sumy bez zmian.
- Korekta XTB (komentarz „corr …”) i „Korekta dywidendy” Bossy → osobna wypłata oznaczona jako korekta, może mieć kwotę ujemną.
- Akcja z USA w Bossie: tytuł podaje ticker („HCA”), a OpenFIGI dla notowań w USD często zwraca wynik niejednoznaczny (bez tickera), sprzedana spółka nie ma już pozycji → wypłata nieprzypisana, liczy się pod tickerem z tytułu.
- Ta sama spółka w XTB i w Bossie, gdy wypłata z Bossy jest nieprzypisana → dwa wiersze w widoku zbiorczym (łączenie z S12 działa tylko na przypisanych).
- Dywidenda w ratach (Atrem: XTB wypłaca 0,72 kilka razy, Yahoo podaje jedną kwotę 2,16) → suma roczna z Yahoo, miesiące mogą się różnić od faktycznych wypłat; flaga rozbieżności (REQ-107).
- Yahoo datuje wypłatę dniem ustalenia prawa (ex-date), nie dniem wypłaty → miesiąc w szacunku może wypaść miesiąc wcześniej niż przelew.
- Dywidenda nadzwyczajna z ostatnich 12 miesięcy → powtórzona w szacunku; metoda tego nie rozpoznaje.
- Akcja z USA w Bossie bez tickera (OpenFIGI niejednoznaczne, #269) → brak danych w szacunku, nazwana w uwagach.
- Spółka z innego kraju notowana w USA (ADR), która jeszcze nic nie wypłaciła → przyrostek „.US” daje regułę 15%, choć faktycznie może być 25–27%; po pierwszej wypłacie obowiązuje stawka z wyciągu.
- Kraj, którego nie ma w wyciągach (np. Belgia) → stawka nieznana, „na konto” liczone brutto, ostrzeżenie (REQ-110).
- Ta sama spółka w IKE i na koncie zwykłym → kwoty sumują się, stawka w wierszu tylko gdy jest ta sama w obu portfelach (REQ-111).

#285:
- Literówka w symbolu → Yahoo nie ma dla niego notowań, nic się nie zapisuje, komunikat z nazwą symbolu (REQ-131).
- Symbol bez waluty, a Yahoo jej nie podaje → zapisany sam symbol; instrument dalej widnieje jako „nieznana waluta notowania”, właściciel może ją dopisać (REQ-131).
- Pozycja Bossy bez bieżącej wartości po imporcie (nieznana waluta notowania, #279) → wykres i tabela wyceniają ją od ceny ostatniej transakcji, przesuwanej notowaniami i kursem z wpisu właściciela; zapisana wartość importu zostaje pusta do następnego importu.
- Dwa instrumenty połączone w jedno aktywo → wpis dotyczy jednego z nich (klucz per broker); drugi ma własne notowania albo własny wpis.
- Instrument z wpisem zostaje sprzedany → wpis zostaje w bazie i dalej wycenia jego historię; z ekranu instrumentów znika razem z instrumentem.

S12:
- OpenFIGI niedostępne przy imporcie (brak FIGI) → nic nie łączy się automatycznie; para trafia do propozycji, jeśli zgadza się ticker albo nazwa (REQ-092).
- Ta sama spółka pod różnymi nazwami i bez wspólnego tickera (np. „PKN Orlen” / „ORLEN”) → podobna nazwa, jeśli jedna zawiera drugą; inaczej właściciel wskazuje ją ręcznie.
- Właściciel połączył A z B, a B z C, potem odłącza B → A i C zostają połączone (REQ-094).
- Nowy import dodaje do aktywa instrument z ISIN → klucz aktywa zmienia się na ten ISIN; przypisania w podziałach zapisane pod starym kluczem dalej się liczą (REQ-095).
- Instrument sprzedany → decyzje o nim zostają w bazie, ale nic nie łączą, dopóki instrument nie wróci.

S11:
- Nowe aktywo z importu → w każdym podziale trafia do „Bez grupy”, dopóki właściciel go nie przypisze.
- Grupa bez żadnej wartości (pusta albo same sprzedane aktywa) → widoczna w edytorze, pominięta na wykresie.
- Usunięcie podziału domyślnego → domyślny wraca do wbudowanego „Klasa aktywów”.

S10:
- Tylko import bez lotów (np. sprzed S10) → historia zaczyna się w dniu importu; ponowny import tego samego eksportu XTB dopisuje loty i cofa początek historii do pierwszego zakupu.
- Sprzedaż i ponowny zakup tego samego instrumentu między dwoma importami → ilość nie przekracza większej z ilości w obu importach (REQ-073); dzień sprzedaży nie jest znany z eksportów.
- Lot otwarty i zamknięty w całości między dwoma importami → niewidoczny (eksport stanu go nie zawiera); dokładny tylko ledger (Bossa).
- Instrument bez notowań (brak tickera, yfinance zablokowane) → wartość stała z kotwicy + ostrzeżenie (REQ-076).
- Split akcji: kurs z yfinance jest skorygowany o splity (bez korekty o dywidendy); ilość z lotów XTB jest bieżąca, więc zgodna; ilość z ledgera Bossy sprzed splitu — nie (znane ograniczenie).

- Ten sam plik XTB wgrany dwa razy → dwa snapshoty z tym samym `valuation_date`; UI pokazuje oba, nie scala automatycznie (właściciel widzi, że coś się powtórzyło, zamiast cichego scalenia niewłaściwych danych).
- Dwa pliki transakcji Bossy z zachodzącymi datami → dedup po hashu wiersza usuwa duplikaty, replay liczy poprawnie (potwierdzone w rozmowie z właścicielem).
- Dwa pliki transakcji Bossy z luką dat między nimi → system tego nie wykryje; REQ-022 daje właścicielowi zakres dat do ręcznej weryfikacji, ale poprawność ostatecznie zależy od dyscypliny eksportu, nie od kodu.
- Ręczna pozycja z ISIN, który da się rozpoznać przez OpenFIGI → tak samo jak pozycja z importu (P1's `_resolve_identifications`), nie osobna ścieżka.
- DuckDB niedostępny na maszynie deweloperskiej (brak AVX2) → blokujące dla portfolio-webapp-S1, patrz Dependencies and risks w 01-story.md.
- Generowanie raportu w trakcie, gdy właściciel klika „generuj” drugi raz zanim pierwszy się skończy → druga prośba czeka na wynik pierwszej, nie odpala równoległego drugiego wywołania LLM dla tego samego snapshotu (unika podwójnego zużycia limitu/kosztu).
- Agregat bez żadnych członków → wartość 0, widoczny w interfejsie, nie błąd.
- Instrument będący członkiem agregatu znika przy kolejnym imporcie (np. sprzedany) → agregat po prostu go nie uwzględnia w sumie, bez błędu; klucz członkostwa (REQ-065) zostaje, gdyby instrument wrócił.
- Próba dodania agregatu do samego siebie pośrednio (A zawiera B, B ma dostać A jako członka) → REQ-062, odrzucone.
- Ten sam instrument dodany bezpośrednio do agregatu A i pośrednio przez zagnieżdżony w A agregat B → REQ-061, liczony raz w wartości A.

## Non-functional requirements

- Performance: import znanego formatu przez API < 2 s (jak P1's CLI); odczyt metryk zapisanego snapshotu < 500 ms.
- Koszt: raport AI dziedziczy koszt z P1 (ASSUMPTION w P1's `02-spec.md`: < 0,10 USD); cache (REQ-041) trzyma liczbę faktycznych wywołań LLM bliską liczbie snapshotów, nie liczbie kliknięć.
- Security and privacy: serwer tylko na `localhost` (REQ-050); dane portfela wyłącznie w `data/private/` (REQ-023); ostrzeżenia o podejrzanych komórkach nigdy nie są filtrowane po drodze (REQ-004).
- Audit and logging: każdy snapshot i każda transakcja zapisują, z jakiego importu pochodzą (plik, czas importu); raport zapisuje model i koszt (REQ-040), tak jak P1's trace.

## Traceability

| AC | REQ |
|---|---|
| AC-1 | REQ-001, REQ-002 |
| AC-2 | REQ-030 |
| AC-3 | REQ-040, REQ-041, REQ-042 |
| AC-4 | REQ-010 |
| AC-5 | REQ-020 |
| AC-6 | REQ-004 |
| AC-7 | REQ-050 |
| AC-8 | REQ-060 |
| AC-9 | REQ-061 |
| AC-10 | REQ-062 |
| AC-11 | REQ-070 |
| AC-12 | REQ-071, REQ-072, REQ-073, REQ-077 |
| AC-13 | REQ-075 |
| AC-14 | REQ-073, REQ-074 |
| AC-15 | REQ-084, REQ-087 |
| AC-16 | REQ-080, REQ-081, REQ-086 |
| AC-17 | REQ-084 |
| AC-18 | REQ-082 |
| AC-19 | REQ-085 |
| AC-20 | REQ-090, REQ-093 |
| AC-21 | REQ-091, REQ-092 |
| AC-22 | REQ-091, REQ-094 |
| AC-23 | REQ-100, REQ-101, REQ-102, REQ-104 |
| AC-24 | REQ-103 |
| AC-25 | REQ-102 |
| AC-26 | REQ-105, REQ-108 |
| AC-27 | REQ-106, REQ-107 |
| AC-28 | REQ-109, REQ-110, REQ-111 |
| AC-29 | REQ-120, REQ-122, REQ-123, REQ-124 |
| AC-30 | REQ-121, REQ-123 |
| AC-31 | REQ-125, REQ-126 |
| AC-32 | REQ-127 |
| AC-33 | REQ-128, REQ-129 |
| AC-34 | REQ-130, REQ-131, REQ-132 |

## Open questions

| # | Question | Owner | Status |
|---|---|---|---|
| 1 | Klucz deduplikacji transakcji — hash pełnego wiersza wystarczy, czy Bossa czasem powtarza identyczne wiersze dla różnych, faktycznie odrębnych transakcji? | Tomasz | otwarte, przed ticketem P1 na Bossę |
| 2 | Limit rozmiaru pliku / liczby pozycji per import | Tomasz | otwarte, jak w P1's `02-spec.md` #4 |
| 3 | Format identyfikatora portfela, gdy w przyszłości będzie ich więcej niż jeden (kilka rachunków?) | Tomasz | otwarte, przed 03-design.md |
| 4 | Format komórki „Open time (UTC)” w prawdziwym eksporcie XTB (data Excela czy tekst, jaki wzorzec)? Parser przyjmuje datę Excela, `DD.MM.RRRR GG:MM:SS` i ISO; nierozpoznany format = brak lotów dla pozycji | Tomasz | otwarte — do sprawdzenia na prawdziwym pliku |
| 5 | Czy arkusz „Closed Positions” z eksportu XTB ma dać dokładną historię także sprzedanych lotów (jak ledger Bossy)? | Tomasz | otwarte, następny krok po S10 |
| 6 | Czy fundusz ma się dać rozbić między kilka grup jednego podziału z wagami (np. VWCE 60% USA / 40% reszta świata)? | Tomasz | otwarte, poza S11 |
| 7 | ~~Ta sama spółka z XTB (klucz `xtb:SYMBOL`, eksport XTB nie ma ISIN) i z Bossy (klucz ISIN) to dziś dwa różne aktywa w podziałach — scalać je?~~ | Tomasz | Odpowiedź: mają być łączone w jedno aktywo; gdy dane nie przesądzają — formularz, w którym właściciel wskazuje/potwierdza parę → S12 (REQ-090..095) |
