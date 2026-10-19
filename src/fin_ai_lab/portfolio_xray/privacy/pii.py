import re

# Header-name heuristic only (decision: no value sniffing for the first
# version, to keep classification deterministic and easy to test).
_PII_HEADER_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"imi[eę]",
        r"nazwisko",
        r"\bname\b",
        r"pesel",
        r"e-?mail",
        r"rachun",  # matches rachunek/rachunku/rachunków (Polish declension)
        r"\baccount\b",
        r"adres",
        r"\baddress\b",
    ]
]

MASKED = "[MASKED]"


def looks_like_pii_header(text: str) -> bool:
    return any(pattern.search(text) for pattern in _PII_HEADER_PATTERNS)


def classify_pii_columns(headers: list[str]) -> list[str]:
    return [header for header in headers if looks_like_pii_header(header)]


def mask_pii_values(
    rows: list[dict[str, object]], pii_columns: list[str]
) -> list[dict[str, object]]:
    masked_rows = []
    for row in rows:
        masked_row = dict(row)
        for column in pii_columns:
            if masked_row.get(column) not in (None, ""):
                masked_row[column] = MASKED
        masked_rows.append(masked_row)
    return masked_rows
