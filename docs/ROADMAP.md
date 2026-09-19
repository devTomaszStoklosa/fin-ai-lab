# Roadmap

Pięć projektów nauki AI engineeringu na danych rynkowych plus fundament wspólny dla wszystkich. Każdy projekt jest epikiem RoleKit; slice'y poniżej to kandydaci na tickety (PO potwierdza podział w `01-story.md`).

## Kolejność i zależności

```mermaid
flowchart LR
  F[lab-foundation<br/>szkielet, klient LLM, harness evali] --> P1[P1 Portfolio X-Ray]
  F --> P2[P2 RAG na raportach]
  F --> P3[P3 Market Pulse]
  F --> P4[P4 Klasyfikator newsów]
  P1 --> P5[P5 Komitet inwestycyjny]
  P2 --> P5
  P3 --> P5
  P4 --> P5
```

1. **lab-foundation** — bez niego każdy projekt budowałby własny klient LLM i własne evale.
2. **P1** — najprostszy start: pojedyncze wywołania, structured outputs, pierwsze evale.
3. **P2 i P3** — w dowolnej kolejności.
4. **P4** — niezależny stack (GPU w chmurze, Python ML); może iść równolegle z P2/P3.
5. **P5** — na końcu, składa wyniki P1–P4 (do testów wystarczą atrapy).

## Umiejętności × projekty

| Umiejętność | Główny projekt | Wraca w |
|---|---|---|
| Prompt engineering, structured outputs | P1 | wszystkie |
| Ewaluacja (golden sety, LLM-as-judge, baseline) | lab-foundation, P1 | wszystkie |
| RAG (parsowanie, chunking, embeddingi, hybrid, reranking, cytaty) | P2 | P5 |
| Tool use, projekt narzędzi, MCP | P3 | P1, P5 |
| Workflow vs agent, orchestrator-workers | P3 | P5 |
| Observability, koszty, prompt caching, Batch API | P3 | P2, P4 |
| Fine-tuning (LoRA/QLoRA), destylacja, jakość danych | P4 | — |
| Multi-agent, context engineering, pamięć, HITL | P5 | — |
| Guardrails, prompt injection | P1 | P2, P5 |

## Slice'y

### lab-foundation (feature M)
- F-1 Szkielet: uv, ruff, pytest, CLI `fin-ai-lab`, test środowiska (AVX2)
- F-2 Konfiguracja z `.env` i klient LLM z liczeniem kosztów oraz trace JSONL
- F-3 Rejestr promptów w plikach z wersjami
- F-4 Harness evali MVP: zbiory JSONL, graderzy, raport, baseline, strażnik kosztów

### P1 Portfolio X-Ray
- P1-S1 Import jednego formatu brokera do schematu kanonicznego (parser deterministyczny = baseline i źródło prawdy)
- P1-S2 LLM tworzy konfigurację parsera dla nieznanego formatu + walidacja z pętlą samokorekty
- P1-S3 Identyfikacja instrumentów przez OpenFIGI (pierwsze narzędzie)
- P1-S4 Silnik metryk portfela (czysty Python)
- P1-S5 Raport opisowy + eval wierności liczb + guardrail „bez rekomendacji" + testy prompt injection
- P1-S6 Wyciągi PDF przez document input
- Później: historia transakcji w DuckDB + text-to-SQL; funkcja portfela w Analizotece (import XTB/Bossa + ręczne wprowadzanie, prezentacja wizualna) z analizą AI z tego repo jako ważnym elementem — po weryfikacji licencji danych i przeniesieniu wyników, patrz README.md

### P2 Zapytaj raport
- P2-S1 Pobranie i parsowanie 10-K (5 spółek) z podziałem na sekcje
- P2-S2 Naiwny RAG + golden set + metryki retrieval i generacji (baseline)
- P2-S3 Hybrid search (BM25 + wektory) + filtry metadanych + reranker
- P2-S4 Contextual retrieval z prompt caching — porównanie z S3
- P2-S5 Router: pytania liczbowe do XBRL, dekompozycja porównań
- P2-S6 Cytaty (Citations API) i poprawne odmowy
- P2-S7 Pytania po polsku i raporty spółek GPW (PDF)
- Później: diff sekcji Risk Factors rok do roku, GraphRAG

### P3 Market Pulse
- P3-S1 Deterministyczne wskaźniki + jedno wywołanie LLM tworzące brief
- P3-S2 Narzędzia + tool runner (pojedynczy agent)
- P3-S3 Własny MCP server z narzędziami danych
- P3-S4 Orchestrator-workers z równoległymi workerami
- P3-S5 Stan między przebiegami, wykrywanie zmian, alert
- P3-S6 Tracing i koszt per przebieg
- P3-S7 Harmonogram (Task Scheduler / GitHub Actions / Managed Agents)
- P3-S8 Evale trajektorii i backtest z anonimizacją dat

### P4 Klasyfikator newsów
- P4-S1 Korpus nagłówków, schemat etykiet, wytyczne etykietowania
- P4-S2 Etykiety teachera (Batch API) + ręczna weryfikacja + zgodność (kappa)
- P4-S3 Baseline'y: klasa większościowa, TF-IDF + regresja logistyczna, few-shot LLM
- P4-S4 Fine-tuning HerBERT (Colab)
- P4-S5 LoRA/QLoRA na małym decoderze (Bielik)
- P4-S6 Kwantyzacja i inferencja na lokalnym CPU
- P4-S7 Raport porównawczy: jakość, koszt, latencja

### P5 Komitet inwestycyjny
- P5-S1 Pojedynczy agent ze wszystkimi narzędziami (baseline)
- P5-S2 Supervisor + role-subagenci ze strukturalnymi briefami
- P5-S3 Kwant: stress testy w sandboxie
- P5-S4 Krytyk (evaluator-optimizer) i wymóg źródeł dla twierdzeń
- P5-S5 Pamięć tez i rozliczanie trafności w czasie
- P5-S6 Human-in-the-loop i budżety
- P5-S7 A/B: komitet vs pojedynczy agent
- Później: UI ze streamingiem (FastAPI + React)

## Budżet API — zasada: zero kosztów (ASSUMPTION — limity RPM/RPD do weryfikacji ręcznie wobec ai.google.dev/gemini-api/docs/pricing)

Klucz Gemini bez billingu: koszt zawsze 0 USD, projekty nie różnią się budżetem w dolarach, tylko presją na limit zapytań darmowego tieru (RPM/RPD).

| Projekt | Presja na darmowy limit | Główne źródło presji |
|---|---|---|
| lab-foundation | niska | testy integracyjne klienta, kilka wywołań |
| P1 | niska–średnia | przebiegi evali importu i raportu |
| P2 | średnia–wysoka | contextual retrieval, evale z wieloma wariantami |
| P3 | niska za przebieg, ale cykliczna | codzienne briefy — throttling musi znać harmonogram |
| P4 | wysoka w S2 (etykiety teachera), potem 0 (fine-tuning lokalny/Colab) | Batch Mode zamiast pojedynczych wywołań, żeby nie wypalić RPD |
| P5 | wysoka | wiele agentów, wiele rund w jednym przebiegu komitetu |

Zero limitu wydatków do ustawienia — klucz zostaje bez billingu. Throttling per model w `core.http`/`core.llm` (patrz [docs/LLM-API.md](LLM-API.md)) pilnuje RPM/RPD, nie budżetu w USD.

## Stan ticketów

| Ticket | 01-story | 02-spec | 03-design | Kod |
|---|---|---|---|---|
| lab-foundation | Ready for dev | Ready for dev | Ready for dev | gotowe (F-1..F-4) |
| p1-portfolio-xray | Ready for architect | Ready for architect | Ready for dev | gotowe (P1-S1..S6, evale zielone) |
| p2-filings-rag | Ready for architect | Ready for architect | Ready for dev | gotowe (P2-S1..S7). Ewale rozszerzone (`refusal_reason`, `has_citations`, pytania PL o GPW) — `p2-retrieval-accuracy` na żywo chwilowo blokowane 503 (przeciążenie Gemini, nie limit) 2026-09-18, do ponowienia |
| p3-market-pulse | Ready for architect | Ready for architect | Ready for dev | gotowe (P3-S1..S8). `p3-regime-backtest` i `p3-trajectory` oba zielone na żywo, baseline zapisane. Harmonogram (S7): skrypty w `scripts/`, rejestracja zadania na maszynie Tomasza czeka na jego uruchomienie |
| p4-news-classifier | Ready for architect | Ready for architect | Ready for dev | P4-S1..S3 gotowe — korpus (92 nagłówki, 4 źródła RSS, rośnie codziennie przez Task Scheduler), etykietowanie teachera przez Groq (drugi provider, ADR 0007; `teacher.v2.md` po naprawie 32%→0% błędów walidacji), wszystkie trzy baseline'y S3 (klasa większościowa, TF-IDF+LR, few-shot LLM). Kalibracja kappa (REQ-011) zrobiona na 86/92 nagłówkach: sentiment 0.461, event_type 0.451 — **poniżej progu 0,6** (główna przyczyna: niejasna granica `makro` vs `inne` w `teacher.v2.md`). Właściciel świadomie przyjął wynik 2026-09-19 bez poprawki promptu — odejście od REQ-011, nie błąd. P4-S4 (HerBERT, Colab) gotowe 2026-09-19: dwa fine-tune (sentiment, event_type) na 92-nagłówkowym korpusie, macro-F1 sentiment 0,254 / event_type 0,049 — model kolabsuje do klasy większościowej (`neutral`/`inne`), zgodnie z zapowiedzią notebooka to sanity check pipeline'u, nie sygnał jakości (korpus zbyt mały). P4-S7 (raport porównawczy) gotowe 2026-09-19: `fin-ai-lab news-classifier compare-report` na 13-nagłówkowym golden set (test-split ∩ human-reviewed) — majority/tfidf/herbert kolabsują do klasy większościowej (macro-F1 0.211/0.152), few-shot LLM wygrywa jakościowo (0.562/0.492) kosztem czasu (p50 2875ms) i pieniędzy (0.33 USD/1000). `torch` (CPU) zweryfikowany na tej maszynie — REQ-021 nie było blokadą. P4-S5 (LoRA/QLoRA na Bielik) kod gotowy 2026-09-19 (`bielik_lora_finetune.ipynb`, `speakleash/Bielik-1.5B-v3.0-Instruct`, Apache 2.0) — czeka na przebieg na żywo w Colab (właściciel). Dalej: P4-S6 (kwantyzacja, lokalny CPU) |
| p5-investment-committee | Ready for architect | Ready for architect | Ready for dev | P5-S1 gotowe (pojedynczy agent, 4 narzędzia — P1/P3 realne, P2/P4 jawne atrapy). Nieuruchomione na żywo, czeka na reset dziennego limitu Gemini (wyczerpany 2026-09-18) |
