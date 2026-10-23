# Aplikacja webowa: interfejs (`frontend`)

> Stan na 2026-10-23, commit `d0c43b4`. Opis sprawdzony w kodzie `frontend/src/` (ok. 7 400 linii). API, z którego korzysta interfejs: [portfolio-webapp.md](portfolio-webapp.md).

## Stos i uruchamianie

React 19, TypeScript 6, Vite 8, linter Oxlint. Poza Reactem **brak zależności wykonawczych**: bez biblioteki wykresów, routera, menedżera stanu ani biblioteki komponentów. Wykresy są rysowane własnym kodem, a widoki przełącza prosty stan w `App.tsx`. Interfejs jest po polsku.

```bash
cd frontend
npm install
npm run dev      # serwer Vite; /api i /health są przekierowywane na http://127.0.0.1:8010
npm run build    # tsc -b && vite build
npm run lint     # oxlint
```

Backend (`uv run fin-ai-lab web`) musi działać na porcie 8010. Proxy zastępuje CORS, bo aplikacja nie ma być dostępna z innych adresów. Projekt nie ma testów interfejsu, a poprawność logiki liczbowej zapewnia backend (testowany w `tests/portfolio_webapp/`).

## Nawigacja: `App.tsx`

Widok to jedna z wartości `View`: `portfolios`, `market-pulse`, `model-comparison`, `filings-qa`, `breakdowns`, `instruments`. Gdy widok to `portfolios`, pokazywany jest `PortfolioDetail` (po wybraniu portfela) albo `Overview`.

Pasek górny pokazuje: nazwę "Portfel", linki do trzech widoków AI (Puls rynku, Porównanie modeli, Zapytaj raport), **licznik zużycia limitu Gemini** (np. "Gemini: 7 / 20 dzisiaj", ostrzeżenie przy 4 lub mniej wywołaniach do końca) i stan backendu. Sprawdzanie stanu ponawia się co 2 sekundy aż do skutku, bo autostart może otworzyć przeglądarkę, zanim backend wstanie. Dopiero po odpowiedzi wczytywane są portfele i zużycie limitu.

## Ekrany

| Ekran | Plik | Zawartość |
|---|---|---|
| Wszystkie portfele | `Overview.tsx` | suma wartości, wykres wartości wszystkich portfeli, lista portfeli, formularz nowego portfela, tabela aktywów, dywidendy, udziały |
| Portfel | `PortfolioDetail.tsx` | wykres wartości portfela, wynik inwestycyjny, pozycje, import pliku, pozycje ręczne i ich wyceny, agregatory, udziały, dywidendy, raport AI, analiza komitetu |
| Podziały | `BreakdownsEditor.tsx` | edycja drzew grup i przypisań instrumentów |
| Instrumenty | `InstrumentLinks.tsx` | łączenie instrumentów z różnych kont, własne symbole Yahoo |
| Puls rynku | `MarketPulse.tsx` | dzisiejszy brief, wskaźniki i reżim, pytanie do agenta |
| Porównanie modeli | `ModelComparison.tsx` | tabela porównawcza klasyfikatorów P4 |
| Zapytaj raport | `FilingsQA.tsx` | spółki w indeksie, pytanie z cytatami |

Makiety poszczególnych ekranów są w artefakcie projektowym opisanym w specyfikacji ([docs/specs/portfolio-webapp/](../specs/portfolio-webapp/)).

## Komponenty

| Obszar | Pliki |
|---|---|
| Wykres wartości i porównanie z indeksem | `ValueChart.tsx` (wykres własny), `BenchmarkPicker.tsx`, `useBenchmark.ts`, `CompareReadout.tsx`, `returns.ts` |
| Wynik inwestycyjny | `investment.ts` (podstawa procentu: wpłaty netto, a przy ich braku koszt zakupów) |
| Pozycje | `PositionsTable.tsx`, `AssetsTable.tsx`, `ManualPosition.tsx`, `ManualValuations.tsx`, `AllocationBars.tsx` |
| Import | `ProposeConfig.tsx` (podgląd konfiguracji proponowanej przez LLM i zatwierdzenie) |
| Dywidendy | `DividendsCard.tsx`, `DividendHistoryPanel.tsx`, `DividendForecastPanel.tsx`, `DividendBars.tsx` |
| Udziały i podziały | `SharesCard.tsx`, `BreakdownsEditor.tsx`, `Aggregators.tsx`, `AggregatorForm.tsx` |
| Instrumenty | `InstrumentLinks.tsx`, `QuoteGaps.tsx` (czego brakuje do wyceny instrumentu, językiem właściciela) |
| AI | `CommitteeAnalysis.tsx` (odpytywanie zadania w tle i okno zgody na budżet), `MarketPulse.tsx`, `FilingsQA.tsx`, `ModelComparison.tsx` |
| Pomocnicze | `api.ts`, `format.ts`, `seriesColors.ts` |

## Warstwa API: `api.ts`

Jeden plik (ok. 1 100 linii) z typami odpowiedzi i funkcjami `fetch*`, `create*`, `update*`, `delete*` odpowiadającymi endpointom backendu. Typy są utrzymywane ręcznie i odzwierciedlają modele z `schemas.py`, więc zmiana kształtu odpowiedzi w backendzie wymaga zmiany w obu miejscach. Importy zgłaszają błędy walidacji jako `ImportFailure` z listami `errors` i `warnings`.

## Konwencje

- **Pieniądze i ilości jako tekst.** Backend wysyła kwoty jako napisy z 8 miejscami po przecinku (`"6.00000000"`). Interfejs nie używa `float` do sum: `format.ts` przelicza na całkowite centy (`toCents`) i formatuje (`formatCents`, `formatMoney`, `formatDecimal`), a nadmiarowe zera są obcinane tylko przy wyświetlaniu. Stopy zwrotu to stosunki, więc tam wystarczą zwykłe liczby (`returns.ts`).
- **Kolory serii.** `seriesColors.ts` daje osiem kolorów sprawdzonych pod kątem daltonizmu. Portfel zachowuje kolor według pozycji na liście, a nie według rangi, więc ukrycie jednego nie przemalowuje reszty. Dziewiąty i kolejne są szare.
- **Pamięć przeglądarki.** Jedyne użycie `localStorage` to zapamiętany wybór indeksu porównawczego (`useBenchmark.ts`), jako wygoda. Brak dostępu do pamięci nie przerywa pracy i wraca wartość domyślna.
- **Jednolity język.** Napisy po polsku z odmianą liczebników (`pluralizePl`), nazwy brokerów (`brokerLabel`) i daty (`formatDate`) w `format.ts`.

## Znane ograniczenia

- Brak testów automatycznych interfejsu i brak typów generowanych z backendu.
- `frontend/README.md` to niezmieniony szablon Vite i nie opisuje tego projektu.
- Aplikacja zakłada backend pod `127.0.0.1:8010`. Zmiana portu wymaga zmiany `vite.config.ts`.
