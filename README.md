# fin-ai-lab

Laboratorium nauki AI engineeringu na danych z rynków finansowych: RAG, praca z LLM i prompt engineering, agenci i orkestracja, fine-tuning, ewaluacja.

> Repo do nauki, nie produkt. Wyniki mogą później trafić do Analizoteki (osobne repo, .NET 10 + React 19) — dopiero po weryfikacji licencji danych i wymogów prawnych.

## Projekty

| # | Projekt | Główny obszar | Ticket (RoleKit) | Stan artefaktów |
|---|---|---|---|---|
| 0 | Fundament: szkielet repo, klient LLM, harness evali | inżynieria, evale | `lab-foundation` | story + spec + design → gotowe dla dev |
| 1 | Portfolio X-Ray — import eksportu z brokera + raport | LLM, prompty, structured outputs, evale | `p1-portfolio-xray` | story + spec → gotowe dla architekta |
| 2 | Zapytaj raport — RAG na sprawozdaniach spółek | RAG | `p2-filings-rag` | story → gotowe dla BA |
| 3 | Market Pulse — agent kondycji rynku | agenci, narzędzia, MCP, observability | `p3-market-pulse` | story → gotowe dla BA |
| 4 | Polski klasyfikator newsów finansowych | fine-tuning, destylacja | `p4-news-classifier` | story → gotowe dla BA |
| 5 | Komitet inwestycyjny — wielu agentów nad portfelem | orkestracja, pamięć, human-in-the-loop | `p5-investment-committee` | story → gotowe dla BA |

Kolejność, zależności i kamienie milowe: [docs/ROADMAP.md](docs/ROADMAP.md).

## Stack

- Python 3.12 · uv · pytest · ruff
- Google Gemini API przez oficjalne SDK `google-genai` — domyślny LLM
- Modele open-weight (Bielik / Qwen) — wyłącznie fine-tuning w projekcie 4, trening w chmurze (Colab / Kaggle)
- Dane: SEC EDGAR, FRED, NBP, GUS BDL, GDELT, RSS, OpenFIGI — [docs/DATA-SOURCES.md](docs/DATA-SOURCES.md)

## Stan

2026-09-14: tylko dokumentacja, brak kodu i repozytorium git. Pierwszy kod powstaje w tickecie `lab-foundation` — jak zacząć: [HANDOFF.md](HANDOFF.md).

## Szybki start (po ukończeniu `lab-foundation`)

```bash
uv sync
cp .env.example .env
uv run pytest -q
```

## Dokumentacja

| Dokument | Zawartość |
|---|---|
| [HANDOFF.md](HANDOFF.md) | stan, decyzje, otwarte pytania, start następnej sesji |
| [CLAUDE.md](CLAUDE.md) | zasady pracy dla Claude Code |
| [docs/ROADMAP.md](docs/ROADMAP.md) | projekty, kolejność, kamienie milowe |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | układ repo, moduły wspólne, przepływy |
| [docs/EVALS.md](docs/EVALS.md) | metodologia ewaluacji |
| [docs/LLM-API.md](docs/LLM-API.md) | Gemini API: modele, koszty, pułapki |
| [docs/DATA-SOURCES.md](docs/DATA-SOURCES.md) | źródła danych, licencje, limity |
| [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) | maszyna deweloperska i jej ograniczenia |
| [docs/LEARNING.md](docs/LEARNING.md) | materiały, słownik, dziennik nauki |
| [docs/adr/](docs/adr/) | decyzje architektoniczne |
| [docs/specs/](docs/specs/) | artefakty RoleKit per ticket |

## Zasady nienegocjowalne

1. Harness evali powstaje przed optymalizacją promptów.
2. Liczby liczy kod; model je objaśnia.
3. Raporty są opisowe — bez spersonalizowanych rekomendacji inwestycyjnych.
4. Sekrety tylko w `.env` (poza gitem); prawdziwe eksporty z brokerów tylko w `data/private/`.
5. Dane z licencją „tylko nauka" nie wychodzą poza to repo.
