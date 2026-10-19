# lab-foundation - Fundament repo: szkielet, klient LLM, harness evali

Status: Ready for dev
Owner role: PO
Upstream: -
Links: docs/ROADMAP.md

## Problem

Właściciel repo (programista .NET / React uczący się AI engineeringu) zaczyna pięć projektów. Bez wspólnego fundamentu każdy projekt budowałby własny klient LLM, własne liczenie kosztów i własne evale: wyniki byłyby nieporównywalne, a koszty niewidoczne. ASSUMPTION: bez harnessu evali strojenie promptów w P1 skończy się zgadywaniem.

## Outcome

Primary metric: droga od „zmieniam prompt" do „widzę wynik względem baseline" — dziś nie istnieje → jedna komenda, poniżej 5 minut dla suity 20 przypadków.
Guardrail metric: 100% wywołań LLM ma zapisany koszt i trace; żaden przebieg nie przekracza limitu kosztów bez zgody.

## User story

Jako właściciel repo uczący się AI engineeringu chcę jedną komendą uruchomić suitę evali dla wybranej wersji promptu i zobaczyć metryki, koszt oraz regresje względem baseline, żeby każda zmiana w projektach P1–P5 była mierzalna.

## Acceptance criteria

- AC-1: Given świeży klon repo i zainstalowane `uv`, when uruchamiam `uv sync` i `uv run pytest -q`, then testy przechodzą bez klucza API i bez sieci.
- AC-2: Given ustawiony `GEMINI_API_KEY`, when kod wywołuje klienta LLM, then wynik zawiera treść, usage, koszt w USD i identyfikator trace, a zdarzenie trafia do pliku w `traces/`.
- AC-3: Given brak `GEMINI_API_KEY`, when uruchamiam komendę wymagającą API, then widzę czytelny błąd konfiguracji z nazwą brakującej zmiennej zamiast stack trace z SDK.
- AC-4: Given suita `foundation-smoke` z deterministycznym celem, when uruchamiam `uv run fin-ai-lab eval foundation-smoke`, then powstaje katalog przebiegu z raportem metryk per grader i per tag oraz plikiem podsumowania.
- AC-5: Given zapisany baseline, when przebieg pogarsza wynik przypadku, then raport wymienia ten przypadek jako regresję.
- AC-6: Given szacowany koszt przebiegu powyżej limitu, when uruchamiam eval, then runner pyta o zgodę (a w trybie nieinteraktywnym przerywa), zanim wyda pieniądze.
- AC-7: Given prompt w rejestrze, when renderuję go bez wymaganej zmiennej, then dostaję błąd wskazujący brakującą zmienną.
- AC-8: Given zależności natywne projektu, when uruchamiam testy, then test środowiska wykrywa, czy każda z nich działa na maszynie bez AVX2.

## Out of scope

- Implementacja któregokolwiek projektu P1–P5.
- Tracing w zewnętrznym narzędziu (Langfuse, Phoenix) — decyzja w P3.
- CI w chmurze.
- Interfejs graficzny do przeglądania wyników.

## Priority

Must have — blokuje wszystkie projekty.

## Dependencies and risks

- Klucz API potrzebny tylko do testów `live` i evali z prawdziwym modelem.
- Ryzyko: przeinżynierowanie harnessu. MVP ma obsłużyć potrzeby P1-S1 i P1-S2; reszta rośnie razem z projektami.
- Ryzyko: paczki natywne niedziałające bez AVX2.

## Open questions

| # | Question | Owner | Due |
|---|---|---|---|
| 1 | Czy repo dostaje remote na GitHubie (prywatny)? | Tomasz | przed pierwszym commitem |
| 2 | Jaki miesięczny limit wydatków API ustawić w Console? | Tomasz | przed wygenerowaniem klucza |
