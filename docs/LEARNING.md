# Nauka

## Jak pracować

1. **Przed slice'em** zapisz hipotezę: co ma się poprawić i jak to zmierzysz.
2. **Najpierw baseline**, potem ulepszenia — każde osobno, z przebiegiem evala.
3. **Po slice'ie** dopisz wpis do dziennika poniżej: liczby, koszt, wnioski, następne pytanie.
4. Gdy technika nie pomaga, to też wynik. Zapisz go.

## Materiały

| Obszar | Materiał |
|---|---|
| Przekrój całości | Chip Huyen, „AI Engineering" (O'Reilly, 2025) |
| Prompty, API, tool use | dokumentacja Google Gemini API (ai.google.dev — prompt engineering, function calling, structured outputs); dokumentacja Anthropic (prompt engineering, tool use) jako materiał koncepcyjny, niezależny od providera; repo `anthropics/courses` na GitHubie |
| Evale | teksty Hamela Husaina o ewaluacji produktów LLM |
| RAG | Anthropic, „Contextual Retrieval" (2024); publikacja FinanceBench (Patronus AI) |
| Agenci | Anthropic, „Building effective agents" (2024); specyfikacja MCP (modelcontextprotocol.io) |
| Fine-tuning | LoRA (Hu i in., 2021); QLoRA (Dettmers i in., 2023); dokumentacja Hugging Face TRL i PEFT; dokumentacja Unsloth |
| Domena | dokumentacja SEC EDGAR i API XBRL; taksonomia US GAAP |

## Słownik

| Termin | Znaczenie |
|---|---|
| RAG | generowanie odpowiedzi na podstawie fragmentów wyszukanych w korpusie |
| Chunk | fragment dokumentu indeksowany osobno |
| Embedding | wektor reprezentujący znaczenie tekstu |
| BM25 | klasyczne wyszukiwanie po słowach kluczowych |
| Hybrid search | połączenie BM25 i wyszukiwania wektorowego |
| Reranker | model porządkujący kandydatów po trafności względem pytania |
| Contextual retrieval | doklejenie do chunka krótkiego kontekstu dokumentu przed indeksowaniem |
| recall@k, MRR | czy właściwy fragment jest w top-k; jak wysoko się pojawia |
| Faithfulness | czy odpowiedź wynika z dostarczonego kontekstu |
| Structured outputs | odpowiedź modelu wymuszona zgodnie ze schematem JSON |
| Tool use | model prosi aplikację o wywołanie funkcji i dostaje wynik |
| MCP | protokół udostępniania narzędzi i danych modelom |
| Workflow vs agent | ścieżka ustalona w kodzie vs ścieżka wybierana przez model |
| Orchestrator-workers | model dzieli zadanie i rozdaje je podwykonawcom |
| Evaluator-optimizer | jeden model ocenia, drugi poprawia, w pętli |
| Prompt caching | ponowne użycie przetworzonego prefiksu promptu — taniej i szybciej |
| Batch API | asynchroniczne przetwarzanie wielu żądań taniej |
| Effort | parametr sterujący głębią rozumowania i zużyciem tokenów |
| LLM-as-judge | model oceniający wyniki według rubryki |
| Golden set | zbiór przypadków z oczekiwanymi wynikami |
| LoRA / QLoRA | dostrajanie małych macierzy adapterów; QLoRA na skwantyzowanym modelu bazowym |
| Destylacja | uczenie małego modelu (student) na wynikach dużego (teacher) |
| DPO | dostrajanie na parach odpowiedzi lepsza / gorsza |
| Kwantyzacja (GGUF) | zapis wag w mniejszej precyzji do szybszej inferencji |
| Kappa Cohena | zgodność dwóch oceniających skorygowana o przypadek |
| Macro-F1 | średnia F1 po klasach, niezależna od liczebności klas |
| Look-ahead bias | test na danych, które model „zna" z przyszłości — tu: z danych treningowych |
| HHI | indeks koncentracji: suma kwadratów wag pozycji |
| VaR historyczny | strata nieprzekroczona z danym prawdopodobieństwem, liczona z historii |
| Max drawdown | największy spadek od szczytu do dołka |
| EARS | szablon zapisu wymagań („When…, the system shall…") |

## Dziennik nauki

Wpis per ukończony slice. Najnowsze na górze.

```markdown
### RRRR-MM-DD — <ticket> / <slice>
- Hipoteza:
- Pomiar (metryka: baseline → wynik, n przypadków):
- Koszt (USD, tokeny, trafienia cache):
- Co zadziałało:
- Co nie zadziałało i dlaczego:
- Następne pytanie:
```

<!-- wpisy poniżej -->
