DEFAULT_CHUNK_SIZE = 1200
DEFAULT_OVERLAP = 150


def chunk_text(
    text: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP
) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= chunk_size or not current:
            current = candidate
            continue
        chunks.append(current)
        current = f"{_tail(current, overlap)}\n\n{paragraph}"

    if current:
        chunks.append(current)

    return _split_oversized(chunks, chunk_size)


def _tail(text: str, overlap: int) -> str:
    return text[-overlap:] if overlap > 0 else ""


def _split_oversized(chunks: list[str], chunk_size: int) -> list[str]:
    # A single paragraph longer than chunk_size wasn't broken up above (it
    # becomes its own chunk on the next iteration) — hard-split just those.
    result: list[str] = []
    for chunk in chunks:
        if len(chunk) <= chunk_size:
            result.append(chunk)
            continue
        for start in range(0, len(chunk), chunk_size):
            result.append(chunk[start : start + chunk_size])
    return result
