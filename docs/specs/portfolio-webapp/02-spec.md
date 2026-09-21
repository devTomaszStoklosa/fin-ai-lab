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

## Actors and permissions

| Actor | Action | Allowed |
|---|---|---|
| Właściciel | wgrywa pliki, dodaje/edytuje/usuwa pozycje ręczne, akceptuje nową konfigurację parsera, generuje raport | tak |
| Właściciel | edytuje pozycję pochodzącą z importu pliku | nie — tylko przez ponowny import |
| P1 (`service.py`, `report/orchestrator.py`) | parsuje pliki, liczy metryki, generuje raport | tak, bez zmian w jego kodzie |
| Sieć spoza localhost | dowolne zapytanie do API | nie — serwer nasłuchuje tylko na localhost |

## Functional requirements (EARS)

Import (reużycie P1)
- REQ-001 (AC-1): When a file is uploaded for a broker with an approved parser configuration in P1's registry, the system shall import it by calling `portfolio_xray.service.import_file` unchanged, not by reimplementing parsing.
- REQ-002 (AC-1): When a file's format signature matches no approved configuration, the system shall offer the same propose/approve flow P1's CLI uses (`on_new_config_proposed`), adapted to two HTTP calls (propose, then approve or reject) instead of a terminal prompt.
- REQ-003: When a file is uploaded for Bossa, the system shall reject it with a clear "not yet supported" error until the separate P1 ledger-aggregation capability exists; it shall never attempt to import Bossa's transaction-history file through the row-mapping path.
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

## Business rules

Wybór ścieżki importu wg brokera

| Broker | Kształt eksportu | Ścieżka |
|---|---|---|
| XTB | stan bieżący (pozycje) | P1's `import_file`, znany format → snapshot |
| inny, nieznany dotąd broker o kształcie pozycji | stan bieżący (pozycje) | P1's propose/approve przez API |
| Bossa | historia transakcji | odrzucone do czasu osobnego ticketu w P1 (REQ-003) |

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
| `dedup_hash` | string | tak, unikalny | hash pełnego wiersza (REQ-021) |
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

## Edge and error cases

- Ten sam plik XTB wgrany dwa razy → dwa snapshoty z tym samym `valuation_date`; UI pokazuje oba, nie scala automatycznie (właściciel widzi, że coś się powtórzyło, zamiast cichego scalenia niewłaściwych danych).
- Plik Bossy wgrany przed ukończeniem osobnego ticketu w P1 → REQ-003, czytelny błąd „format nieobsługiwany”, nie próba importu przez ścieżkę pozycji.
- Dwa pliki transakcji Bossy z zachodzącymi datami → dedup po hashu wiersza usuwa duplikaty, replay liczy poprawnie (potwierdzone w rozmowie z właścicielem).
- Dwa pliki transakcji Bossy z luką dat między nimi → system tego nie wykryje; REQ-022 daje właścicielowi zakres dat do ręcznej weryfikacji, ale poprawność ostatecznie zależy od dyscypliny eksportu, nie od kodu.
- Ręczna pozycja z ISIN, który da się rozpoznać przez OpenFIGI → tak samo jak pozycja z importu (P1's `_resolve_identifications`), nie osobna ścieżka.
- DuckDB niedostępny na maszynie deweloperskiej (brak AVX2) → blokujące dla portfolio-webapp-S1, patrz Dependencies and risks w 01-story.md.
- Generowanie raportu w trakcie, gdy właściciel klika „generuj” drugi raz zanim pierwszy się skończy → druga prośba czeka na wynik pierwszej, nie odpala równoległego drugiego wywołania LLM dla tego samego snapshotu (unika podwójnego zużycia limitu/kosztu).

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

## Open questions

| # | Question | Owner | Status |
|---|---|---|---|
| 1 | Klucz deduplikacji transakcji — hash pełnego wiersza wystarczy, czy Bossa czasem powtarza identyczne wiersze dla różnych, faktycznie odrębnych transakcji? | Tomasz | otwarte, przed ticketem P1 na Bossę |
| 2 | Limit rozmiaru pliku / liczby pozycji per import | Tomasz | otwarte, jak w P1's `02-spec.md` #4 |
| 3 | Format identyfikatora portfela, gdy w przyszłości będzie ich więcej niż jeden (kilka rachunków?) | Tomasz | otwarte, przed 03-design.md |
