# 0004. Evale najpierw, prompty w plikach z wersjami

Status: Accepted

## Context

Zmiany promptów bez pomiaru prowadzą do regresji, których nikt nie zauważa. Wyniki evali są porównywalne tylko wtedy, gdy wiadomo, która wersja promptu, zbioru i modelu je dała.

## Decision

- Harness evali powstaje w `lab-foundation`, przed pierwszym promptem produkcyjnym.
- Prompty jako pliki `prompts/<id>.v<N>.md`; zmiana treści = nowy plik. Kod odwołuje się do `(id, version)`.
- Suity mają `dataset_version`; baseline jest przypięty do wersji promptu, modelu i zbioru.
- Zmiana promptu, modelu lub pipeline'u nie jest skończona bez przebiegu suity i porównania z baseline.
- Kontrakt i zasady: [EVALS.md](../EVALS.md).

## Consequences

- Pozytywne: każda zmiana ma liczby; regresje widać per przypadek; łatwe A/B wersji.
- Negatywne: więcej plików; każdy przebieg kosztuje — stąd cache wyników i strażnik kosztów.

## Alternatives considered

- **Prompty jako stałe w kodzie** — prostsze, ale historia zmian miesza się z kodem, a baseline nie wie, co mierzył.
- **Gotowe narzędzie (promptfoo, Braintrust, Langfuse datasets)** — do rozważenia później; własny harness uczy, co taki system musi robić.
