# p2-filings-rag - Zapytaj raport: RAG na sprawozdaniach spółek

Status: Ready for ba
Owner role: PO
Upstream: -
Links: docs/ROADMAP.md, docs/DATA-SOURCES.md

## Problem

Sprawozdanie 10-K ma ponad 100 stron, raport okresowy spółki z GPW podobnie. Odpowiedź na konkretne pytanie zajmuje godzinę, porównanie rok do roku — więcej. Ogólny chatbot zmyśla liczby i nie wskazuje źródła. Dla właściciela to projekt nauki pełnego pipeline'u RAG i jego ewaluacji. ASSUMPTION: korpus 5–20 spółek wystarcza do nauki.

## Outcome

Primary metric: recall@5 ≥ 0,9 i poprawność odpowiedzi ≥ 85% na golden secie; baseline mierzony w P2-S2.
Guardrail metric: 0 odpowiedzi liczbowych bez cytatu źródła; ≥ 90% trafnych odmów na pytaniach bez odpowiedzi w korpusie.

## User story

Jako inwestor analizujący spółkę chcę zadać pytanie o jej sprawozdania po polsku lub angielsku i dostać odpowiedź z cytatami ze źródła, żeby szybko sprawdzić fakty bez czytania całego raportu.

## Acceptance criteria

- AC-1: Given zaindeksowane 10-K spółki, when pytam o fakt opisowy (np. główne czynniki ryzyka), then dostaję odpowiedź z cytatem wskazującym dokument, sekcję i fragment.
- AC-2: Given pytanie o wartość raportowaną w XBRL (np. przychody za rok), when pytam, then liczba pochodzi z danych XBRL z okresem i jednostką, a nie z tekstu wygenerowanego przez model.
- AC-3: Given pytanie porównawcze rok do roku, when pytam, then odpowiedź zestawia oba okresy z cytatem dla każdego.
- AC-4: Given pytanie, na które korpus nie zawiera odpowiedzi, when pytam, then system mówi, że nie znalazł odpowiedzi, zamiast zgadywać.
- AC-5: Given pytanie po polsku o dokument angielski, when pytam, then odpowiedź jest po polsku, a cytaty w oryginale.
- AC-6: Given pytanie o spółkę spoza korpusu, when pytam, then dostaję informację o braku danych dla tej spółki.
- AC-7: Given dokument z tekstem przypominającym polecenia dla modelu, when fragment trafia do kontekstu, then polecenie nie zmienia zachowania systemu.

## Out of scope

- Rekomendacje inwestycyjne.
- Newsy i dane bieżące.
- Spółki spoza SEC EDGAR i ręcznie pobranych raportów GPW.
- Interfejs graficzny.

## Priority

Should (po P1). MVP cut line: P2-S1 do P2-S4 oraz P2-S6. P2-S5 — Should. P2-S7 — Could.

## Slices

| Slice | Wartość dla użytkownika | Czego uczy |
|---|---|---|
| P2-S1 Pobranie i parsowanie 10-K z sekcjami | korpus gotowy do pytań | parsowanie HTML, tabele, metadane |
| P2-S2 Naiwny RAG + golden set | pierwsze odpowiedzi i ich zmierzona jakość | chunking stały, embeddingi, metryki retrieval i generacji |
| P2-S3 Hybrid search + filtry + reranker | trafniejsze fragmenty | BM25, fuzja wyników, filtry metadanych, reranking |
| P2-S4 Contextual retrieval | mniej chybionych wyszukiwań | kontekst chunków, prompt caching, pomiar kosztu |
| P2-S5 Router do XBRL + dekompozycja | liczby z danych, porównania okresów | routing zapytań, dane strukturalne obok RAG |
| P2-S6 Cytaty i odmowy | weryfikowalne odpowiedzi | Citations API, ocena odmów |
| P2-S7 Pytania po polsku + raporty GPW | polskie spółki i język | wyszukiwanie międzyjęzykowe, PDF |

## Dependencies and risks

- Wymaga `lab-foundation`.
- SEC wymaga nagłówka `User-Agent` z kontaktem (`SEC_USER_AGENT`).
- Tabele w HTML i PDF to najtrudniejsza część parsowania.
- Embeddingi na CPU bez AVX2 mogą być wolne lub niedostępne — alternatywa Voyage API.
- Citations nie działa razem ze structured outputs w jednym wywołaniu.
- Synonimiczne tagi XBRL (np. trzy nazwy przychodów) — patrz docs/DATA-SOURCES.md.
- Licencja FinanceBench do sprawdzenia przed użyciem poza nauką.

## Open questions

| # | Question | Owner | Due |
|---|---|---|---|
| 1 | Które spółki w korpusie? Propozycja: 5 dużych z US + 3 z GPW | Tomasz | przed P2-S1 |
| 2 | Embeddingi: Voyage (koszt) czy lokalny model (CPU)? Decyzja architekta po pomiarze | Architect | P2-S2 |
| 3 | Źródło polskich sprawozdań: PDF z relacji inwestorskich czy KRS/eKRS? | Tomasz | przed P2-S7 |
