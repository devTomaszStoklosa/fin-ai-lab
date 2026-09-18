# 0007. Groq jako drugi provider LLM (obok Gemini)

Status: Accepted

## Context

ADR 0003 świadomie odrzucił wielu dostawców za warstwą abstrakcji: "jeden dostawca (Gemini) bez warstwy abstrakcji multi-provider — świadoma decyzja właściciela, nie architektura na zapas". Ta decyzja trzymała się, dopóki darmowy tier Gemini (`gemini-3.6-flash`: RPD=20, zweryfikowane realnym 429 — patrz [LLM-API.md](../LLM-API.md)) nie stał się realną blokadą: P4-S2 (etykietowanie teachera, docelowo 300-500 nagłówków) i codzienne uruchomienia P5 (komitet inwestycyjny) nie mieszczą się w 20 wywołaniach/dzień, a zasada zero kosztów (CLAUDE.md, punkt 9) wyklucza podpięcie billingu jako rozwiązania.

Właściciel repo poprosił o research alternatyw i zgodził się na implementację bez doprecyzowania szczegółów technicznych (odpowiedź: "nie wiem, implementuj") — decyzje projektowe poniżej podjęte przez Claude Code na podstawie zebranego researchu, nie wprost podyktowane przez właściciela.

## Decision

- Nowy `GroqLlmClient` w `src/fin_ai_lab/core/llm/groq_client.py`, implementujący ten sam `LlmClient` protocol co `GeminiLlmClient` (`async def complete(request: LlmRequest) -> LlmResult`) — **drugi provider obok Gemini, nie zamiennik**. Żaden istniejący pipeline (P1-P5) nie został przełączony na Groq w tym ticketcie; to infrastruktura gotowa do użycia, wybór "który projekt/slice używa którego providera" zostaje osobną decyzją.
- Model: `openai/gpt-oss-120b` (i `openai/gpt-oss-20b` jako tańszy wariant) — `llama-3.3-70b-versatile`, pierwotnie rekomendowany w research, okazał się zdjęty z darmowego tieru Groq (deprecated 2026-06-17, enterprise-only od 2026-08-26 — zweryfikowane live web search, nie z pamięci). Sprawdź `console.groq.com/docs/models` przed użyciem, na wypadek kolejnej zmiany.
- Klucz w `.env` jako `GROQ_API_KEY`, bez podpiętego billingu — ta sama zasada zero kosztów co dla Gemini (CLAUDE.md, punkt 9). Ceny w `core/llm/pricing.py` (`PRICES`) to stawki płatnego tieru Groq, używane wyłącznie jako tripwire fail-safe (`FIN_AI_LAB_MAX_RUN_COST_USD=0`), nie realny mechanizm rozliczeniowy — identyczna rola jak ceny Gemini.
- **Ręczna pętla tool-calling**, nie automatic function calling (AFC) jak w Gemini: Groq nie gwarantuje po stronie SDK automatycznej wieloturowej pętli dla dowolnych własnych narzędzi Python (potwierdzone przez oficjalną dokumentację — server-side orchestration istnieje tylko dla wybranych trybów jak `groq/compound` czy remote MCP, nie dla zwykłych `tools=[...]`). `GroqLlmClient` sam buduje schemat JSON z sygnatur/docstringów narzędzi (`_tool_schema`), woła API, wykonuje zwrócone `tool_calls`, dokłada wyniki do historii wiadomości i powtarza — z twardym limitem `MAX_TOOL_ITERATIONS=8` jako fail-safe przeciw nieskończonej pętli (model uporczywie proszący o narzędzia).
- `groq_client` jako opcjonalny parametr konstruktora `GroqLlmClient` (injection seam) — w odróżnieniu od `GeminiLlmClient`, gdzie `genai.Client` jest budowany wewnętrznie i nietestowany jednostkowo (tylko `test_llm_client_live.py`). Uzasadnienie: `GroqLlmClient` zawiera własną, nietrywialną logikę (pętla, budowa schematu, fail-safe iteracji), więc zasługuje na testy jednostkowe bez sieci — `GeminiLlmClient` jest cienkim wrapperem, gdzie jedyna sensowna weryfikacja jest żywa.
- Nowy extras `groq` w `pyproject.toml` (`groq>=1.7.0`) — pakiet czysto pythonowy (REST, kompatybilny z OpenAI Chat Completions), bez ryzyka AVX2, więc bez wpisu w `tests/test_environment.py`/`docs/ENVIRONMENT.md` (ten sam wzorzec co ekstra `pulse`/`mcp`, patrz `docs/ENVIRONMENT.md` — zasada dotyczy zależności **natywnych**).

## Consequences

- Pozytywne: druga, niezależna pula limitów darmowego tieru — realnie odblokowuje P4-S2/S3 i codzienne użycie P5 bez czekania na reset Gemini. Struktura zgodna z `LlmClient` protocol, więc każdy istniejący kod przyjmujący `LlmClient` (P1-P5, evale) może dostać `GroqLlmClient` przez wstrzyknięcie zależności bez zmian w sygnaturach.
- Negatywne: to jednak odwrócenie części ADR 0003 ("bez warstwy abstrakcji multi-provider") — teraz dwa providery istnieją równolegle, throttling w `core.http`/`core.llm` musi docelowo rozróżniać limity per-provider (nie zrobione w tym ticketcie, throttling nadal nieegzekwowany proaktywnie dla żadnego z providerów — patrz LLM-API.md).
- Jakość modeli GPT-OSS (Groq) dla polskich tekstów finansowych (P2 GPW, P4 nagłówki PL) nieprzebadana evalami — przed produkcyjnym użyciem w konkretnym projekcie wymagany eval porównawczy z Gemini (rule 1, CLAUDE.md).
- Jeśli część korpusu P4 zostanie kiedyś oznaczona przez teachera Groq zamiast Gemini, dataset traci spójność etykiet (dryf stylu między modelami wygląda jak szum) — jeśli Groq zostanie użyty jako teacher, powinien oznaczyć **cały** pozostały korpus, nie tylko część.
- `GroqLlmClient.complete()` liczy koszt sumując tokeny ze wszystkich tur pętli tool-calling (poprawka względem znanej niedokładności `GeminiLlmClient`, gdzie AFC zwraca `usage_metadata` tylko dla ostatniej wewnętrznej tury — patrz komentarz w `core/llm/client.py`).

## Alternatives considered

- **Zamiana Gemini na Groq w całym repo** — odrzucone: unieważnia już zebrane etykiety teachera P4 i kalibrację kappa (zmiana teachera w trakcie), jakość Llama/GPT-OSS dla polskich tekstów nieprzebadana, wymagałoby przepisania każdego promptu dostrojonego pod Gemini.
- **OpenRouter** (agregator wielu providerów) — niższy RPD niż Groq w darmowym tierze bez doładowania, dodatkowa warstwa pośrednika (routing, inny kształt odpowiedzi zależny od wybranego modelu bazowego).
- **Cerebras** — od lipca 2026 darmowy tier wymaga karty kredytowej, łamie zasadę "bez karty"/zero kosztów tego repo.
- **Nowy projekt Google Cloud z osobnym kluczem Gemini** zamiast innego providera — odrzucone: limity RPD są per-projekt, ale wielokrotne konta/projekty tego samego właściciela pod jednym adresem e-mail to praktyka bliższa obejściu ToS niż legalne zwiększenie budżetu; niezależny provider jest czystszym rozwiązaniem.
