# 0006. Raporty opisowe, bez rekomendacji inwestycyjnych

Status: Proposed

## Context

P1, P3 i P5 generują teksty o portfelach i rynku. Spersonalizowana rekomendacja dotycząca instrumentów finansowych to w UE doradztwo inwestycyjne (MiFID II), w Polsce wymagające zezwolenia KNF. Wyniki repo mogą w przyszłości trafić do Analizoteki, więc zasada obowiązuje od początku.

## Decision

- Raporty opisują fakty i ryzyko: skład, koncentrację, ekspozycje, scenariusze, rozbieżności opinii. Nie mówią „kup", „sprzedaj", „zwiększ", „zmniejsz", „powinieneś".
- Instrukcja w promptach systemowych + dwa graderzy w evalach: `forbidden` (frazy) i `llm_judge` z rubryką „brak rekomendacji".
- Każdy raport kończy stała stopka: informacja, że to analiza edukacyjna, a nie rekomendacja inwestycyjna.

## Consequences

- Pozytywne: bezpieczna ścieżka do ewentualnego użycia w produkcie; przy okazji uczymy się guardraili i ich ewaluacji.
- Negatywne: raporty mniej „akcyjne"; część pytań użytkownika (np. „co kupić?") dostaje odmowę z wyjaśnieniem.

## Alternatives considered

- **Rekomendacje z disclaimerem** — disclaimer nie zmienia kwalifikacji prawnej spersonalizowanej rekomendacji.
- **Brak zasady w repo do nauki** — wynik trudno byłoby potem przenieść do produktu.
