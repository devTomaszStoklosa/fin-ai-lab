# 0005. Maszyna tylko z CPU bez AVX2: lekki stack lokalnie, GPU w chmurze

Status: Accepted

## Context

Maszyna deweloperska: Intel i5-2500K (AVX, brak AVX2), 8 GB RAM, brak GPU NVIDIA, Windows 10 (szczegóły: [ENVIRONMENT.md](../ENVIRONMENT.md)). Część binarnych paczek ML wymaga AVX2; ciężkie usługi (lokalny Langfuse, bazy wektorowe w Dockerze) konkurują o RAM.

## Decision

- Wyszukiwanie wektorowe w `numpy` (brute force) dla korpusów tego repo; biblioteka indeksów dopiero po teście importu i potrzebie.
- Embeddingi: API (Voyage) albo małe modele lokalne z cache na dysku.
- Tracing: pliki JSONL; Phoenix lokalnie albo Langfuse Cloud — decyzja w P3.
- Fine-tuning i inferencja GPU: Google Colab / Kaggle. Lokalnie tylko inferencja encodera i małych skwantyzowanych modeli, z pomiarem latencji.
- Każda zależność natywna ma test importu w `tests/test_environment.py`.

## Consequences

- Pozytywne: repo działa na obecnym sprzęcie; ograniczenia są jawne i testowane.
- Negatywne: brak lokalnych eksperymentów z dużymi modelami; zależność od limitów darmowych GPU w chmurze — nie tylko godzin GPU, ale też czasu trwania i ciągłości sesji (Colab potrafi ubić sesję po kilkunastu godzinach ciągłej pracy, po dłuższej bezczynności albo losowo odciąć GPU przy dużym obciążeniu serwerów). Zasada zero kosztów (patrz ADR 0003) wyklucza płatny Colab Pro jako obejście — trening w P4 musi zapisywać checkpointy wystarczająco często, żeby przerwana sesja nie kasowała całej dotychczasowej pracy.
- Decyzję warto zrewidować przy zmianie sprzętu.

## Alternatives considered

- **Qdrant / Langfuse w Dockerze** — wygodne, ale 8 GB RAM nie wystarczy na nie razem z resztą.
- **Płatna instancja GPU (np. RunPod)** — możliwa dla P4-S5, jeśli darmowe limity okażą się za małe.
- **WSL2 z Ubuntu** — nie rozwiązuje braku AVX2 ani GPU.
