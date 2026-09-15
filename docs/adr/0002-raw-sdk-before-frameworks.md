# 0002. Surowe SDK przed frameworkami

Status: Accepted

## Context

Celem repo jest zrozumienie mechanizmów: pętli narzędzi, zarządzania kontekstem, retrieval, kosztów. Frameworki (LangChain, LangGraph, LlamaIndex, PydanticAI, CrewAI) ukrywają te mechanizmy za abstrakcjami i szybko się zmieniają. Anthropic w „Building effective agents" zaleca zaczynać od bezpośrednich wywołań API — zasada dotyczy każdego dostawcy, nie tylko Anthropic.

## Decision

- Wywołania modelu przez oficjalne SDK `google-genai`, opakowane cienko w `core.llm`.
- Pętle agentów najpierw ręcznie, potem tool runner z SDK (beta) — oba warianty w P3 dla porównania.
- Framework wchodzi tylko po ADR, który podaje: jaki problem rozwiązuje, co zyskujemy vs własny kod i jak zmierzono różnicę.

## Consequences

- Pozytywne: pełna kontrola nad promptem, kosztami i trace'ami; wiedza przenośna między frameworkami.
- Negatywne: więcej własnego kodu (runner evali, pętla narzędzi, retrieval).
- Świadomie odkładamy naukę konkretnego frameworka — można ją dodać jako osobny slice porównawczy.

## Alternatives considered

- **LangGraph od początku** — gotowe grafy stanów i checkpointy, ale abstrakcje zasłaniają to, czego chcemy się nauczyć.
- **LlamaIndex dla P2** — szybki start RAG, ale chunking, retrieval i ocena są właśnie przedmiotem nauki.
- **Gotowe SDK agentowe providera (np. Vertex AI Agent Builder)** — sensowne jako porównanie w P3 i P5, nie jako fundament.
