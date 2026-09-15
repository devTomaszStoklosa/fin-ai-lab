# 0001. Python 3.12, uv i jeden pakiet z podpakietami per projekt

Status: Proposed

## Context

Repo mieści pięć projektów nauki AI engineeringu i wspólny rdzeń (klient LLM, evale, klienci danych). Ekosystem AI (SDK, narzędzia RAG, fine-tuning, evale) jest najpełniejszy w Pythonie. Właściciel na co dzień pracuje w .NET i React, więc liczy się mała liczba nowych pojęć. Maszyna nie ma AVX2 (patrz [ENVIRONMENT.md](../ENVIRONMENT.md)).

## Decision

- Python 3.12 (`uv python pin 3.12`), uv jako menedżer projektu.
- Jeden pakiet `fin_ai_lab` w `src/`, podpakiety: `core`, `portfolio_xray`, `filings_rag`, `market_pulse`, `news_classifier`, `committee`.
- Zależności projektów jako extras (`rag`, `pulse`, `ml`, `ui`) — domyślna instalacja zostaje lekka.
- Narzędzia: pytest, ruff (lint + format).

## Consequences

- Pozytywne: jeden `uv sync`, proste importy z `core`, jedno miejsce konfiguracji testów i lintu.
- Negatywne: projekty nie mają twardych granic zależności — pilnuje ich przegląd kodu i zasada „projekty nie importują się nawzajem" (wyjątek: P5 przez `service.py`).
- Trening modeli w P4 i tak odbywa się w notebookach w chmurze, poza tym środowiskiem.

## Alternatives considered

- **uv workspace z członkiem per projekt** — twardsze granice, ale więcej konfiguracji i pojęć na start. Do rozważenia, jeśli extras zaczną się konfliktować.
- **.NET (Semantic Kernel, oficjalne SDK C#)** — znany stack, ale uboższy ekosystem RAG, evali i fine-tuningu; fine-tuning i tak wymagałby Pythona.
- **Python 3.13** — dostępny lokalnie, ale węższe wsparcie kół binarnych ML; brak zysku dla tego repo.
