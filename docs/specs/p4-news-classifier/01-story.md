# p4-news-classifier - Polski klasyfikator newsów finansowych

Status: Ready for architect
Owner role: PO
Upstream: -
Links: docs/ROADMAP.md, docs/DATA-SOURCES.md, docs/LLM-API.md

## Problem

Polskie serwisy finansowe publikują setki nagłówków dziennie (ok. 150–300 z dwóch kanałów RSS — dane z Analizoteki). Ton medialny z GDELT jest dla polskich tekstów liczony na tłumaczeniu maszynowym, więc sygnał jest zaszumiony. Duży model językowy dla każdego nagłówka jest za drogi i za wolny przy tym wolumenie. Dla właściciela to projekt nauki pełnego cyklu fine-tuningu i destylacji.

## Outcome

Primary metric: macro-F1 sentymentu ≥ 0,80 i typu zdarzenia ≥ 0,75 na ręcznie etykietowanym, najnowszym chronologicznie zbiorze testowym, przy koszcie na 1000 newsów co najmniej 10× niższym niż teacher (ASSUMPTION).
Guardrail metric: macro-F1 małego modelu nie więcej niż 5 p.p. poniżej few-shot LLM; zero przecieków między zbiorami.

## User story

Jako osoba śledząca polski rynek chcę, żeby każdy nagłówek finansowy dostał sentyment, typ zdarzenia i powiązane spółki, żeby filtrować i agregować newsy bez czytania wszystkich.

## Acceptance criteria

- AC-1: Given nagłówek po polsku, when go klasyfikuję, then dostaję sentyment (negatywny / neutralny / pozytywny z perspektywy akcjonariuszy), typ zdarzenia z zamkniętej listy i tickery spółek z katalogu.
- AC-2: Given nagłówek o spółce spoza katalogu, when go klasyfikuję, then lista tickerów jest pusta zamiast zgadniętej.
- AC-3: Given nagłówek niezwiązany z rynkiem, when go klasyfikuję, then typ zdarzenia to `other`, a sentyment `neutral`.
- AC-4: Given wytrenowany model, when uruchamiam go na lokalnym CPU, then poznaję latencję p50 i p95 oraz koszt na 1000 newsów.
- AC-5: Given ręcznie etykietowany zbiór testowy, when porównuję modele, then raport pokazuje macro-F1, macierz pomyłek, latencję i koszt dla baseline'ów, teachera i modeli dostrojonych.
- AC-6: Given niepoprawny składniowo wynik modelu generatywnego, when klasyfikuję, then system zwraca błąd z kategorią zamiast częściowych danych.

## Out of scope

- Pełne treści artykułów — tylko tytuł i lead do 150 znaków.
- Publikacja modelu lub zbioru danych.
- Języki inne niż polski (angielskie zbiory tylko jako materiał pomocniczy).
- Serwowanie produkcyjne.

## Priority

Should. Niezależny od P2 i P3. MVP cut line: P4-S1 do P4-S4 oraz P4-S7. P4-S5 i P4-S6 — Should.

## Slices

| Slice | Wartość dla użytkownika | Czego uczy |
|---|---|---|
| P4-S1 Korpus, schemat etykiet, wytyczne | wiadomo, co i jak klasyfikujemy | projektowanie etykiet, higiena danych |
| P4-S2 Etykiety teachera + weryfikacja ręczna | zbiór treningowy i testowy | Batch API, structured outputs, kappa Cohena |
| P4-S3 Baseline'y | punkt odniesienia | klasa większościowa, TF-IDF + regresja logistyczna, few-shot LLM |
| P4-S4 Fine-tuning HerBERT | szybki klasyfikator | fine-tuning encodera w Colab |
| P4-S5 LoRA/QLoRA na małym decoderze | porównanie z generatywnym | PEFT, Unsloth / TRL, wyjście JSON |
| P4-S6 Kwantyzacja i lokalny CPU | model działa bez chmury | GGUF, pomiar latencji |
| P4-S7 Raport porównawczy | wybór modelu na liczbach | ewaluacja jakości, kosztu i latencji |

## Dependencies and risks

- Wymaga `lab-foundation`; GPU w chmurze (Colab / Kaggle).
- Licencje zbiorów (FinancialPhraseBank: niekomercyjna) i checkpointów modeli.
- Warunki Google dotyczące trenowania modeli na wynikach usług Gemini API — patrz docs/LLM-API.md.
- Jakość etykiet teachera ogranicza jakość ucznia — stąd ręczna weryfikacja.
- Split chronologiczny i deduplikacja prawie identycznych nagłówków są konieczne, inaczej wynik będzie zawyżony.
- Przypadki zdarzeń rzadkich (np. kara regulatora) mogą mieć za mało przykładów.

## Open questions

| # | Question | Owner | Due |
|---|---|---|---|
| 1 | Teacher: Gemini (sprawdzić warunki) czy etykiety ręczne + teacher open-weight? | Tomasz | przed P4-S2 |
| 2 | Ile nagłówków zweryfikujesz ręcznie? Propozycja: 300–500 | Tomasz | przed P4-S2 |
| 3 | Zatwierdzić listę typów zdarzeń? Propozycja: wyniki finansowe, dywidenda, emisja akcji, skup akcji, przejęcie lub fuzja, zmiana w zarządzie, prognoza, decyzja lub kara regulatora, spór prawny, umowa lub kontrakt, rekomendacja lub rating, makro, inne | Tomasz | przed P4-S1 |
