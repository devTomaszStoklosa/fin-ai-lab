# HANDOFF — fin-ai-lab

Data: 2026-09-19, P2 (`filings_rag`) i P3 (`market_pulse`) ukończone, P4 (`news_classifier`) S1-S7 gotowe (Groq jako drugi provider LLM, ADR 0007; kalibracja kappa REQ-011 zrobiona, wynik poniżej progu 0,6, właściciel świadomie przyjął; S4 HerBERT fine-tune na Colab, macro-F1 sentiment 0,254 / event_type 0,049; S5 LoRA/QLoRA na `speakleash/Bielik-1.5B-v3.0-Instruct` — 0/13 błędów schematu, macro-F1 sentiment 0,254 / event_type 0,235; oba dostrojone modele kolabsują do klasy większościowej na 92-nagłówkowym korpusie, ten sam pipeline-sanity-check wniosek co S4; S6 kwantyzacja GGUF + lokalna inferencja CPU wykonana end-to-end, `llama-cpp-python` zweryfikowany na tej maszynie, REQ-021 co do metodologii latencji spełnione — ale skwantyzowany model generuje pustą odpowiedź, znany bug konwersji wokabularza llama.cpp, [issue #142](https://github.com/devTomaszStoklosa/fin-ai-lab/issues/142), nienaprawiany dalej; S7 raport porównawczy pięciu modeli — few-shot LLM wygrywa jakościowo, resztę zjada class imbalance na małym korpusie), P5 (`investment_committee`) BA spec + architekt gotowe, S1-S2 gotowe i odpalone na żywo na prawdziwym portfelu XTB (S2: supervisor + 3 role-subagenci, orchestrator-workers) (sekcja "Stan" i "Stan ticketów" w [ROADMAP.md](docs/ROADMAP.md) zaktualizowane; reszta pliku, w tym "Start następnej sesji", pochodzi z pierwszej sesji 2026-09-14 i częściowo nie jest już aktualna — patrz `docs/ROADMAP.md` dla realnego stanu ticketów).
Źródło: sesja Claude Code uruchomiona w `C:\Users\Tomasz\Desktop\Repo` (Analizoteka), bez RoleKit. Pamięć Claude z tamtej sesji nie jest widoczna w tym katalogu — wszystko, co potrzebne, jest w tym repo.

## Kontekst

- Właściciel: Tomasz — twórca Analizoteki (.NET 10 + React 19), uczy się AI engineeringu.
- Cel repo: nauka RAG, pracy z LLM i prompt engineeringu, agentów i orkestracji, fine-tuningu oraz ewaluacji na pięciu projektach z rynków finansowych.
- Pochodzenie: pięć propozycji projektów omówionych w rozmowie 2026-09-14. Sesja pełniła role PO, BA i Architekta (lite) i zapisała artefakty w formacie RoleKit, żeby kolejne sesje mogły pracować rolami.

## Stan

| Obszar | Stan |
|---|---|
| Kod | `lab-foundation`, P1 (`portfolio_xray`), P2 (`filings_rag`), P3 (`market_pulse`) i P4 (`news_classifier`, S1-S7) gotowe; P5 (`investment_committee`) S1 gotowe, czeka na realny test na żywo — patrz [ROADMAP.md](docs/ROADMAP.md) „Stan ticketów" |
| Git | repozytorium istnieje, publiczny remote [devTomaszStoklosa/fin-ai-lab](https://github.com/devTomaszStoklosa/fin-ai-lab), praca przez ticket+branch+PR |
| Dokumentacja | README, CLAUDE.md, dokumenty w `docs/`, ADR-y, specyfikacje RoleKit per projekt w `docs/specs/` |
| Artefakty RoleKit | patrz `docs/ROADMAP.md` „Stan ticketów" — bardziej aktualne niż ten wiersz |
| Konfiguracja | `.claude/rolekit.json`, `.gitignore`, `.env` (nie w repo) |
| Klucze API | `GEMINI_API_KEY` i `SEC_USER_AGENT` ustawione w `.env` na maszynie właściciela; darmowy tier bez billingu |

## Decyzje

| Decyzja | Uzasadnienie |
|---|---|
| Python 3.12 + uv, jeden pakiet `fin_ai_lab` z podpakietami per projekt | [ADR 0001](docs/adr/0001-python-uv-single-package.md) |
| Surowe SDK `google-genai` przed frameworkami | [ADR 0002](docs/adr/0002-raw-sdk-before-frameworks.md) |
| Google Gemini API jako główny LLM (świadomie darmowy tier); open-weight tylko do fine-tuningu | [ADR 0003](docs/adr/0003-gemini-api-primary-open-weights-finetuning.md) |
| Evale najpierw, prompty w plikach z wersjami | [ADR 0004](docs/adr/0004-evals-first-versioned-prompts.md) |
| Maszyna bez AVX2 i GPU: lekki stack lokalnie, trening w chmurze | [ADR 0005](docs/adr/0005-cpu-only-machine-cloud-gpu.md) |
| Raporty opisowe, bez rekomendacji inwestycyjnych | [ADR 0006](docs/adr/0006-descriptive-reports-no-investment-advice.md) |
| Repo w `AI Lab\fin-ai-lab` obok RoleKit; dokumentacja po polsku, kod i prompty po angielsku | [CLAUDE.md](CLAUDE.md) |

## Kroki właściciela przed pierwszym kodem

1. Przejrzyj `docs/specs/lab-foundation/` i ADR-y. Zaakceptuj (ADR: `Status: Accepted`) albo zgłoś poprawki.
2. W katalogu repo: `git init -b main` i pierwszy commit dokumentacji. Bramki RoleKit wymagają gita.
3. Utwórz klucz API w Google AI Studio, skopiuj `.env.example` do `.env` i wpisz klucz jako `GEMINI_API_KEY`. Klucz FRED (darmowy) wystarczy przed P3.
4. Odpowiedz na pytania blokujące poniżej.

## Otwarte pytania

Blokujące:

| # | Pytanie | Blokuje |
|---|---|---|
| 1 | ~~Czy repo dostaje prywatny remote na GitHubie?~~ Odpowiedź: publiczny remote, [devTomaszStoklosa/fin-ai-lab](https://github.com/devTomaszStoklosa/fin-ai-lab) | pierwszy push — zrobiony |
| 2 | ~~Miesięczny limit wydatków API?~~ Odpowiedź: zero kosztów — klucz Gemini bez podpiętego billingu, `FIN_AI_LAB_MAX_RUN_COST_USD=0` jako fail-safe, patrz [docs/LLM-API.md](docs/LLM-API.md) | klucz API, testy `live` — odblokowane |
| 3 | Eksporty których brokerów masz i w jakich formatach? Odpowiedź: XTB i Bossa (Dom Maklerski BOŚ); format wciąż nieznany, przykładowe pliki dosłane później | P1-S1 — częściowo odblokowane |

Pozostałe pytania są w sekcjach „Open questions" artefaktów: [lab-foundation](docs/specs/lab-foundation/02-spec.md), [P1](docs/specs/p1-portfolio-xray/02-spec.md), [P2](docs/specs/p2-filings-rag/01-story.md), [P3](docs/specs/p3-market-pulse/01-story.md), [P4](docs/specs/p4-news-classifier/01-story.md), [P5](docs/specs/p5-investment-committee/01-story.md).

## Start następnej sesji

### Rekomendowane: RoleKit, rola Dev dla `lab-foundation`

Z katalogu repo:

```bash
claude --plugin-dir "C:\Users\Tomasz\Desktop\AI Lab\rolekit"
```

W sesji uruchom `/rolekit:role dev` (Dev nie ma agenta w RoleKit), potem wklej:

```
Continue lab-foundation: read docs/specs/lab-foundation/ and start the dev workflow.
```

### Wariant z bramkami akceptacji

Ustaw `Status: Approved` w `docs/specs/lab-foundation/01-story.md`, `02-spec.md` i `03-design.md`, potem `/rolekit:flow lab-foundation Fundament repo` — flow zacznie od planu Deva.

### Bez RoleKit

Otwórz Claude Code w katalogu repo i napisz: „Przeczytaj HANDOFF.md i docs/specs/lab-foundation/, potem zacznij slice F-1 z 03-design.md."

### Kolejne tickety (po `lab-foundation`)

| Ticket | Następna rola | Start |
|---|---|---|
| `p1-portfolio-xray` | Architect | `claude --agent rolekit:architect` → `Continue p1-portfolio-xray: read docs/specs/p1-portfolio-xray/ and start the architect workflow.` |
| `p2-filings-rag` … `p5-investment-committee` | BA | `claude --agent rolekit:ba` → `Continue <ticket>: read docs/specs/<ticket>/ and start the ba workflow.` |

Każdy projekt P1–P5 to epik. Przy starcie pracy nad slice'em rozważ osobny ticket (np. `p1-s1-known-format-import`), zgodnie z triage RoleKit dla epików.

## Definicja ukończenia `lab-foundation`

- `uv sync` i `uv run pytest -q` przechodzą bez klucza API i bez sieci.
- `uv run ruff check .` bez błędów.
- `uv run fin-ai-lab eval foundation-smoke` tworzy raport; przebieg z `--save-baseline` zapisuje baseline; kolejny przebieg pokazuje delty.
- `tests/test_environment.py` sprawdza zależności natywne, a wyniki są w tabeli w `docs/ENVIRONMENT.md`.
- Bramki `gates.dev` i `gates.qa` ustawione w `.claude/rolekit.json`.
- Wpis w dzienniku nauki (`docs/LEARNING.md`).

## Pułapki

- CPU bez AVX2: najpierw test importów, potem architektura na paczce ([ENVIRONMENT.md](docs/ENVIRONMENT.md)).
- Launcher `py` startuje Pythona 3.13t — używaj `uv run`.
- Ścieżka repo zawiera spację — cytuj ją.
- Brak tu lokalnego skilla źródła prawdy dla Gemini (jak `claude-api` dla Anthropic) — przed kodem API sprawdź [LLM-API.md](docs/LLM-API.md) i oficjalną dokumentację ai.google.dev, nie zgaduj kształtu API z pamięci.
- Do czasu utworzenia klucza API wszystko działa na `FakeLlmClient`.
- Linię `Status:` w artefaktach czyta skrypt RoleKit — nie zmieniaj jej formatu.
- Duże heredoki w Git Bash kończą się błędem — zapisuj skrypty do plików.
- Nie commituj bez prośby właściciela.

## Mapa dokumentów

| Dokument | Po co |
|---|---|
| [README.md](README.md) | przegląd projektów i stacku |
| [CLAUDE.md](CLAUDE.md) | zasady pracy dla Claude Code |
| [docs/ROADMAP.md](docs/ROADMAP.md) | kolejność, slice'y, budżet, stan ticketów |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | układ repo i kontrakty `core` |
| [docs/EVALS.md](docs/EVALS.md) | metodologia i kontrakt evali |
| [docs/LLM-API.md](docs/LLM-API.md) | modele, koszty, pułapki API |
| [docs/DATA-SOURCES.md](docs/DATA-SOURCES.md) | źródła, licencje, limity |
| [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) | maszyna i jej ograniczenia |
| [docs/LEARNING.md](docs/LEARNING.md) | materiały, słownik, dziennik nauki |
