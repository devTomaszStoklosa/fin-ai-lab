import re

_INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"ignore (all|any|the)?\s*(previous|above)\s*instructions",
        r"zignoruj\s*(poprzedni|wszystkie|powyższ)",
        r"disregard\s*(all|any|the)?\s*(previous|above)\s*instructions",
        r"you are now",
        r"jeste[sś] teraz",
        r"system prompt",
        r"new instructions?:",
        r"nowe instrukcje:",
    ]
]


def looks_like_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


def flag_suspicious_cells(rows: list[tuple[object, ...]]) -> list[str]:
    """Scan raw rows (1-indexed by position in the list) for cells whose text
    resembles an instruction aimed at a model. Works without knowing which
    row is a header or what the columns are named — every cell is checked."""
    flags = []
    for row_number, row in enumerate(rows, start=1):
        for column_index, value in enumerate(row):
            if isinstance(value, str) and looks_like_injection(value):
                column_letter = _column_letter(column_index)
                flags.append(f"row {row_number}, column {column_letter}: '{value}'")
    return flags


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
