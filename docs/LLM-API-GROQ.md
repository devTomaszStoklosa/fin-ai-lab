# Groq API — drugi provider LLM, zasady i pułapki

Drugi provider obok Gemini (patrz [LLM-API.md](LLM-API.md), [ADR 0007](adr/0007-groq-secondary-llm-provider.md)) — **nie zamiennik**, tylko dodatkowa, niezależna pula darmowego tieru. Podobnie jak przy Gemini: brak tu lokalnego skilla będącego źródłem prawdy, sprawdzaj [console.groq.com/docs](https://console.groq.com/docs) przed każdą zmianą, dane poniżej wymagają weryfikacji na 2026-09-18.

## Konto i klucz

- Klucz API z [console.groq.com/keys](https://console.groq.com/keys) — darmowy tier developerski, bez karty kredytowej.
- Klucz tylko w `.env` jako `GROQ_API_KEY`. Nigdy nie wklejaj go w czacie, kodzie ani trace'ach — ta sama zasada co dla `GEMINI_API_KEY`.

## Zero kosztów

Ta sama zasada co dla Gemini (patrz LLM-API.md): klucz bez podpiętego billingu, `FIN_AI_LAB_MAX_RUN_COST_USD=0` to fail-safe na wypadek anomalii, nie realny mechanizm ochronny. Ceny w `core/llm/pricing.py` (`openai/gpt-oss-120b`, `openai/gpt-oss-20b`) to stawki płatnego tieru Groq — służą wyłącznie jako tripwire.

## Modele (ASSUMPTION — zweryfikuj w console.groq.com/docs/models przed użyciem)

- `llama-3.3-70b-versatile` — **zdjęty z darmowego tieru** (deprecated 2026-06-17, enterprise-only od 2026-08-26). Jeśli research/dokumentacja gdzieś jeszcze go rekomenduje, to nieaktualne.
- `openai/gpt-oss-120b` — model domyślny w `GroqLlmClient` dla zadań wymagających jakości. Wspiera tool use i structured output.
- `openai/gpt-oss-20b` — tańszy/szybszy wariant, wybór po evalu, jak przy Gemini.
- Limity RPM/RPD są **per organizacja, nie per klucz** (potwierdzone oficjalną dokumentacją) i różnią się per model — sprawdź panel konta (`console.groq.com`, zakładka limitów), publiczne blogi podają sprzeczne liczby.

## Pułapki

1. **Brak automatic function calling (AFC).** W przeciwieństwie do `google-genai`, Groq nie gwarantuje po stronie SDK automatycznej wieloturowej pętli dla własnych narzędzi Python — `GroqLlmClient` implementuje tę pętlę sam (`core/llm/groq_client.py`, `MAX_TOOL_ITERATIONS=8` jako fail-safe). Przy zmianie tego klienta pamiętaj, że "kiedy skończyć pętlę" to nasza odpowiedzialność, nie SDK.
2. **API kompatybilne z OpenAI Chat Completions** — kształt `messages`/`tools`/`tool_calls` różni się od Gemini (`role`+`content`, nie `role`+`parts`; `system` jako pierwsza wiadomość, nie osobne pole `system_instruction`). `GroqLlmClient` robi konwersję z jednolitego `LlmRequest` na ten kształt.
3. **Structured output** przez `response_format={"type": "json_object"}` — słabsza gwarancja niż Gemini's `response_schema` (typowany schemat po stronie API); walidacja i tak dzieje się po stronie klienta (`response_schema.model_validate_json`), tak samo jak w Gemini fallback path.
4. **Argumenty narzędzi zawsze parsuj jako JSON** (`json.loads(call.function.arguments)`) — nigdy nie porównuj surowego tekstu, ta sama zasada co dla Gemini.
5. Rate limit przekroczony → HTTP 429 z nagłówkiem `retry-after` — throttling proaktywny w `core.http`/`core.llm` per-provider nie jest jeszcze wdrożony dla Groq (tak jak nie jest w pełni wdrożony dla Gemini, patrz LLM-API.md) — planuj przebiegi z tym w pamięci.

## Warunki użycia

Sprawdź aktualne warunki Groq przed użyciem produkcyjnym lub jako teacher (destylacja) — nie zakładaj, że są identyczne z Gemini. Jeśli Groq zostanie użyty jako teacher w P4, powinien oznaczyć cały pozostały korpus, nie tylko część — mieszanie teacherów psuje spójność etykiet (patrz ADR 0007, sekcja Consequences).

## SDK

`uv sync --extra groq` (extras `groq`, pakiet `groq>=1.7.0`, czysto pythonowy klient REST — `from groq import AsyncGroq`). Sprawdź aktualną wersję i changelog przed aktualizacją — brak tu lokalnego skilla z gotowym przewodnikiem migracji, tak jak dla Gemini.
