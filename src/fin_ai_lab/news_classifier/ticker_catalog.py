# Ticker -> company name, manually maintained (02-spec.md open question #4,
# resolved in 03-design.md): no free, automatable full WSE ticker list
# exists — gpw.pl/spolki blocks plain HTTP requests (bot-protected) and
# stooq.pl is excluded the same way (both checked live, docs/DATA-SOURCES.md).
# Seeded with the companies already known from P2/P3; tickers verified live
# against Yahoo Finance (query1.finance.yahoo.com), 2026-09-18 — extend by
# hand as needed, never scrape gpw.pl/stooq to grow this.
TICKER_CATALOG: dict[str, str] = {
    "ATR": "Atrem",
    "PKN": "PKN Orlen",
    "ING": "ING Bank Śląski",
}
