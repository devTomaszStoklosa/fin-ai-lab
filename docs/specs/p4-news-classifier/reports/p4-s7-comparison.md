# P4-S7: raport porównawczy — baseline'y vs HerBERT

REQ-020: macro-F1 (sentiment, event type), koszt/1000 nagłówków, latencja p50/p95, na tym samym zbiorze testowym (chronologiczny test-split ∩ human-reviewed, REQ-022 — żaden model nie widział tych nagłówków w treningu/few-shot).

## Podsumowanie

| Model | n | sentiment macro-F1 | event_type macro-F1 | koszt/1000 (USD) | latency p50 (ms) | latency p95 (ms) |
|---|---|---|---|---|---|---|
| majority | 13 | 0.211 | 0.152 | 0.0000 | 0.0 | 6.0 |
| tfidf | 13 | 0.211 | 0.152 | 0.0000 | 0.0 | 40.4 |
| few-shot | 13 | 0.562 | 0.492 | 0.3284 | 2875.0 | 12831.2 |
| herbert | 13 | 0.211 | 0.152 | 0.0000 | 468.0 | 12494.2 |

## Klasy bez wsparcia w zbiorze testowym

REQ-020 edge case: rzadkie typy zdarzeń zgłoszone tu, nie ukryte uśrednieniem (docs/EVALS.md zasada 5) — macro-F1 powyżej liczy się tylko po klasach z support > 0.
- **majority**: brak przykładów dla: wyniki finansowe, dywidenda, emisja akcji, skup akcji, przejęcie lub fuzja, zmiana w zarządzie, decyzja lub kara regulatora, umowa lub kontrakt
- **tfidf**: brak przykładów dla: wyniki finansowe, dywidenda, emisja akcji, skup akcji, przejęcie lub fuzja, zmiana w zarządzie, decyzja lub kara regulatora, umowa lub kontrakt
- **few-shot**: brak przykładów dla: wyniki finansowe, dywidenda, emisja akcji, skup akcji, przejęcie lub fuzja, zmiana w zarządzie, decyzja lub kara regulatora, umowa lub kontrakt
- **herbert**: brak przykładów dla: wyniki finansowe, dywidenda, emisja akcji, skup akcji, przejęcie lub fuzja, zmiana w zarządzie, decyzja lub kara regulatora, umowa lub kontrakt
