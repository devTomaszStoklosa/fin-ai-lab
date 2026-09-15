# 0003. Google Gemini API jako główny LLM, modele open-weight tylko do fine-tuningu

Status: Proposed

## Context

Projekty P1–P3 i P5 potrzebują silnego modelu do ekstrakcji, rozumowania i pracy z narzędziami. P4 wymaga pełnego procesu fine-tuningu (dane, LoRA, pętla treningowa, kwantyzacja), którego nie da się przećwiczyć na zamkniętym modelu przez API.

Pierwotnie repo zakładało Claude API jako głównego dostawcę (patrz historia tego dokumentu). Właściciel repo zdecydował się na Google Gemini API, w tym jego darmowy tier, ze świadomą akceptacją, że w darmowym tierze Google może wykorzystywać przesyłane dane do trenowania swoich modeli (patrz LLM-API.md, sekcja „Warunki użycia").

## Decision

- Domyślny model: `gemini-2.5-pro`. Tańsze/szybsze modele (`gemini-2.5-flash`, `gemini-2.5-flash-lite`) tylko po evalu pokazującym, że jakość się trzyma. ID modeli zweryfikuj przed użyciem w [ai.google.dev](https://ai.google.dev) — w repo nie ma lokalnego skilla będącego źródłem prawdy, jak przy Claude.
- Fine-tuning (P4): modele open-weight — encoder HerBERT oraz mały decoder (Bielik lub Qwen) — trenowane w Colab/Kaggle. Bez zmian względem poprzedniej decyzji.
- Wszystkie wywołania Gemini przez `core.llm`; szczegóły API w [LLM-API.md](../LLM-API.md).
- Jeden dostawca (Gemini) bez warstwy abstrakcji multi-provider — świadoma decyzja właściciela, nie architektura na zapas.

## Consequences

- Pozytywne: jeden dostawca API upraszcza klienta, cache i koszty; darmowy tier obniża próg wejścia do nauki; P4 uczy pełnego cyklu treningu niezależnie od wyboru dostawcy API.
- Negatywne: koszty/limity API zależą od jednego dostawcy; porównanie z innymi modelami zamkniętymi poza zakresem; darmowy tier ma niższe limity RPM/RPD niż płatny — evale i przebiegi trzeba tak planować.
- Dane wysyłane w darmowym tierze mogą być wykorzystane przez Google do trenowania modeli — do danych prywatnych (eksporty brokerów, dane osobowe) używaj wyłącznie danych syntetycznych/zanonimizowanych albo przejdź na płatny tier, patrz LLM-API.md.
- Etykiety teachera z Gemini w P4 podlegają warunkom Google dotyczącym API — przed produkcyjnym użyciem przeczytaj aktualne warunki, patrz LLM-API.md, sekcja „Warunki użycia".

## Alternatives considered

- **Kilku dostawców przez warstwę abstrakcji** — więcej kodu i słabsze wykorzystanie funkcji specyficznych dla providera (cache, structured outputs); odrzucone na życzenie właściciela repo.
- **Wyłącznie modele lokalne** — maszyna bez GPU i AVX2 (patrz ADR 0005) wyklucza to w praktyce.
- **Claude API** — pierwotny wybór tego ADR; odrzucony, bo właściciel repo chce korzystać wyłącznie z Google Gemini.
