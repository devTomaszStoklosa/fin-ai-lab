# Google Gemini API — zasady i pułapki

Skrót na potrzeby tego repo. **W przeciwieństwie do Claude API, tu nie ma lokalnego skilla będącego źródłem prawdy** — przed pisaniem lub zmianą kodu wywołującego Gemini sprawdzaj oficjalną dokumentację [ai.google.dev/gemini-api/docs](https://ai.google.dev/gemini-api/docs). Modele, ceny i limity poniżej pochodzą z wiedzy modelu na styczeń 2026 i **wymagają weryfikacji przed każdym szacunkiem kosztów** — Google zmienia nazwy modeli i limity darmowego tieru częściej niż Anthropic.

## Konto i klucz

- Klucz API z [Google AI Studio](https://aistudio.google.com/app/apikey).
- Klucz tylko w `.env` jako `GEMINI_API_KEY`. SDK czyta go sam.
- **Nigdy nie wklejaj klucza w czacie, kodzie, notebooku ani trace'ach.** Jeśli klucz kiedykolwiek trafi gdzie indziej niż `.env` (np. wklejony w rozmowę), traktuj go jako skompromitowany i wygeneruj nowy w AI Studio.

## Zero kosztów — zasada tego repo

- Klucz Gemini w tym repo **nigdy nie ma podpiętego billingu** w Google Cloud/AI Studio. Konsekwencja: przekroczenie darmowego limitu (RPM/RPD) kończy się błędem (np. 429/resource exhausted), nie obciążeniem karty — nie ma jak automatycznie przejść na płatne rozliczenie bez billingu.
- `FIN_AI_LAB_MAX_RUN_COST_USD=0` w `.env` to fail-safe, nie realny mechanizm ochronny: skoro koszt zawsze wychodzi zero, sam limit w dolarach niczego nie pilnuje na co dzień. Jego rola to złapać anomalię — gdyby koszt kiedykolwiek wyszedł > 0, przebieg ma się zatrzymać i zapytać, a nie ciągnąć dalej po cichu.
- Realną ochronę ciągłości przebiegu daje throttling w `core.http`/`core.llm`: limit zapytań na minutę dopasowany do RPM konkretnego modelu w darmowym tierze, nie reagowanie dopiero na błąd 429. Sprawdź aktualny RPM/RPD modelu w `ai.google.dev` przed ustawieniem throttlingu — różni się per model i bywa jednocyfrowy dla mocniejszych modeli.
- Embeddingi, tracing i inne usługi pomocnicze: wybieraj domyślnie darmowe opcje (embeddingi Gemini, lokalne trace JSONL) — patrz sekcja „Embeddingi" niżej i `.env.example`.

## Darmowy tier a dane

- Darmowy tier: limity RPM/RPD/TPM per model (niższe niż płatny), zwykle brak opłat do tych limitów.
- **W darmowym tierze Google może wykorzystywać przesyłane dane (prompty, załączniki, odpowiedzi) do trenowania swoich modeli.** W płatnym tierze (billing włączony w Google Cloud/AI Studio) dane nie są używane do treningu.
- Konsekwencja dla tego repo: dane prywatne (prawdziwe eksporty z brokerów, dane osobowe) wysyłaj do Gemini tylko z płatnego tieru albo używaj wyłącznie danych syntetycznych/zanonimizowanych w darmowym tierze. Decyzja właściciela repo: świadomie akceptuje to ryzyko dla nauki na danych syntetycznych/publicznych — patrz [ADR 0003](adr/0003-gemini-api-primary-open-weights-finetuning.md).

## Modele (ASSUMPTION — zweryfikuj w ai.google.dev przed użyciem)

| Model | ID | Kontekst | Rola w repo |
|---|---|---|---|
| Gemini 2.5 Pro | `gemini-2.5-pro` | ~1M | domyślny — rozumowanie, ekstrakcja, narzędzia |
| Gemini 3.6 Flash | `gemini-3.6-flash` | ~1M | workery, sędziowie — po pomiarze |
| Gemini 2.5 Flash-Lite | `gemini-2.5-flash-lite` | ~1M | masowa klasyfikacja — po pomiarze |

- `gemini-2.5-flash` przestał być dostępny dla nowych kluczy API (potwierdzone 2026-09-16 realnym wywołaniem — 404 "no longer available to new users", z odsyłaczem do `gemini-3.6-flash`). Jeśli inny model z tabeli też zacznie zwracać 404, sprawdź `ai.google.dev/gemini-api/docs/models` przed podstawieniem czegokolwiek na pamięć.
- ID podawaj dokładnie jak zwraca `ai.google.dev` (Google czasem dodaje sufiksy wersji, np. `-latest` albo datę — sprawdź, czy repo ma się do nich przypinać, czy śledzić najnowszą).
- **Darmowy tier `gemini-3.6-flash`: tylko 20 wywołań `generate_content` na DZIEŃ** (zweryfikowane realnym 429: `quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue: 20`), nie na minutę — mocno ograniczające dla evali z wieloma przypadkami odpalanych tego samego dnia. `core.http`/`core.llm` nie throttlują dziś pod ten limit (SDK samo ponawia 429, ale nie czeka godzinami do resetu dziennego limitu) — planuj przebiegi evali z tym w pamięci, nie zakładaj że 5-10 przypadków dziennie zawsze przejdzie.
- Tańszy/szybszy model to decyzja poparta evalem, nie domysł — analogicznie do zasady z Claude.
- Ceny za token: sprawdź aktualną tabelę na [ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing) przed każdym szacunkiem — nie przepisuj tu migawki, bo szybko się dezaktualizuje.

## Pułapki (do zweryfikowania w dokumentacji — brak tu lokalnego skilla)

1. Structured outputs: `generation_config.response_mime_type = "application/json"` + `response_schema` (Pydantic/JSON Schema) — inny kształt niż `output_config.format` w Anthropic. Sprawdź aktualne nazwy pól SDK przed pisaniem `core.llm`.
2. Function calling / tool use: `tools` z `FunctionDeclaration`, wynik zwracany jako `function_call` w odpowiedzi — parsuj strukturalnie, nie tekstowo, tak jak w regule dla Anthropic.
3. Myślenie/rozumowanie (modele „thinking”, np. 2.5 Pro/Flash): sterowane `thinking_config` (np. `thinking_budget`) — nazwy pól i limity per model zmieniają się, zweryfikuj przed użyciem; nie zgaduj z pamięci.
4. System instruction to osobne pole (`system_instruction`), nie pierwsza wiadomość w `messages` jak w części innych API.
5. Bezpieczeństwo: domyślne `safety_settings` mogą ucinać odpowiedzi (`finish_reason = SAFETY`) na neutralnych finansowo promptach (liczby, nazwy spółek) — zawsze sprawdzaj `finish_reason` przed czytaniem treści, analogicznie do `stop_reason` w Anthropic.
6. Context caching (odpowiednik prompt caching) działa inaczej niż u Anthropic — jawne tworzenie `cachedContent` z TTL, nie automatyczne dopasowanie prefiksu. Sprawdź próg minimalnej długości przed poleganiem na nim.
7. Batch Mode (odpowiednik Batch API) — asynchroniczne, taniej; łącz wyniki po własnym identyfikatorze, tak jak `custom_id` w Anthropic.
8. Limity darmowego tieru są per model i dość niskie (RPM potrafi być jednocyfrowe dla mocniejszych modeli) — evale i przebiegi wsadowe planuj z throttlingiem w `core.http`/`core.llm`, nie zakładaj przepustowości płatnego tieru.
9. Argumenty narzędzi zawsze parsuj jako JSON — nigdy nie porównuj surowego tekstu (uniwersalna zasada, nie tylko dla Anthropic).

## Dźwignie kosztów (kolejność)

1. **Context caching** — jeśli dostępne dla modelu i wystarczająco długi kontekst.
2. **Batch Mode** — taniej, asynchronicznie, gdy wynik nie musi być natychmiastowy.
3. **Niższy „effort"/mniejszy budżet myślenia** — dla prostych zadań i subagentów, jeśli model to wspiera.
4. **Higiena wejścia i wyjścia** — nie wysyłaj zbędnego kontekstu, ogranicz długość odpowiedzi.
5. **Tańszy/szybszy model** — dopiero gdy eval pokaże, że jakość się trzyma.

Audyt kosztów istniejącego kodu: brak lokalnego skilla — przejrzyj ręcznie wywołania `core.llm` i porównaj z cennikiem `ai.google.dev`.

## Funkcje API per projekt

| Projekt | Funkcje |
|---|---|
| P1 | structured outputs, wejście PDF (multimodalne), tool use (OpenFIGI) |
| P2 | context caching (contextual retrieval), Batch Mode — cytaty budowane własnym kodem (Gemini nie ma odpowiednika Citations API — sprawdź aktualny stan w dokumentacji) |
| P3 | function calling, własny MCP server, context caching, Batch Mode |
| P4 | Batch Mode + structured outputs (etykiety teachera) |
| P5 | function calling wieloagentowe — code execution / memory tool sprawdź dostępność w aktualnej dokumentacji Gemini, funkcje i nazwy różnią się od Anthropic |

## Embeddingi

Gemini udostępnia własny model embeddingów, w tym w darmowym tierze — inaczej niż Anthropic, które nie ma własnego modelu embeddingów. Alternatywy zostają dostępne: Voyage AI (wariant finansowy) albo modele open-source (BGE-M3, multilingual-e5, MMLW dla polskiego) — te ostatnie z uwagą na CPU bez AVX2.

Użyty w P2 (`core/llm/embeddings.py`, zweryfikowane 2026-09-16): `gemini-embedding-2` — jedyny model embeddingów wciąż wyceniony na `ai.google.dev/gemini-api/docs/pricing` ($0.20/1M tokenów wejścia, darmowy tier istnieje); `gemini-embedding-001` nadal odpowiada na żywe wywołanie i wsparłby `task_type` (`RETRIEVAL_DOCUMENT`/`RETRIEVAL_QUERY`, lepsze dla asymetrycznego retrieval), ale zniknął z aktualnej strony cenowej — po historii z `gemini-2.5-flash` (patrz `PRICES` w `core/llm/pricing.py`) wybrany model, który dokumentacja wciąż aktywnie opisuje, nie ten, który akurat jeszcze odpowiada. `gemini-embedding-2` nie wspiera `task_type`; wielotekstowe wywołanie wymaga owinięcia każdego tekstu w osobny `types.Content`, inaczej API agreguje wszystkie teksty w jeden wektor (zweryfikowane empirycznie, nieudokumentowane wprost). SDK nie zwraca liczby tokenów dla `embed_content` (`metadata`/`statistics` puste) — koszt liczony z szacunku znaki/4, nie z realnego usage.

**Darmowy tier `gemini-embedding-2`: limit liczy TEKSTY w batchu, nie wywołania API** — jedno wywołanie z dokładnie 100 tekstami 429uje natychmiast, jedno z 1 tekstem przechodzi (zweryfikowane 2026-09-16, `quotaId: EmbedContentRequestsPerMinutePerUserPerProjectPerModel-FreeTier`, `quotaValue: 100`, ale mierzone per-tekst nie per-request — nieudokumentowane wprost na `ai.google.dev`). `GeminiEmbeddingClient` dzieli batch po `MAX_BATCH_SIZE=20` i tempuje kolejne wywołania proporcjonalnie do rozmiaru poprzedniego (`seconds_per_item`, domyślnie 60/80 z zapasem) — indeksowanie kilkuset fragmentów realnie trwa kilka minut, nie sekund.

## Warunki użycia

- Warunki Google dla Gemini API mogą ograniczać wykorzystanie wyników do trenowania **konkurencyjnych** modeli AI — sprawdź aktualne warunki przed produkcyjnym użyciem, szczególnie dla P4 (destylacja/etykiety teachera). Alternatywa: etykiety ręczne albo teacher open-weight.
- W darmowym tierze Google może wykorzystywać przesyłane dane do trenowania własnych modeli — patrz sekcja „Darmowy tier a dane" wyżej.
- Do API nie wysyłaj danych identyfikujących osoby (imiona, numery rachunków z eksportów brokera) — minimalizacja danych, niezależnie od tieru.

## SDK

- `uv add google-genai` (oficjalne SDK Google dla Gemini API). Sprawdź wymaganą wersję Pythona i ewentualne przewodniki migracji w oficjalnej dokumentacji — brak tu lokalnego skilla z gotowym przewodnikiem zmian.
- Używaj typów z SDK zamiast własnych definicji wiadomości i narzędzi.
