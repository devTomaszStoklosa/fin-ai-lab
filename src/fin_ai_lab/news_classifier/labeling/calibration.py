from collections import Counter


def cohens_kappa(a: list[str], b: list[str]) -> float:
    """REQ-011 / docs/EVALS.md calibration: agreement between two labelers
    on the same categorical dimension (e.g. sentiment, or event_type —
    call this once per dimension, kappa is inherently single-variable).
    `tickers` (a set, not a category) isn't a fit for kappa — compare those
    with set overlap (e.g. Jaccard) instead, not this function."""
    if len(a) != len(b):
        raise ValueError("a and b must be the same length")
    n = len(a)
    if n == 0:
        return 1.0

    p_observed = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n

    counts_a = Counter(a)
    counts_b = Counter(b)
    categories = set(counts_a) | set(counts_b)
    p_expected = sum((counts_a.get(c, 0) / n) * (counts_b.get(c, 0) / n) for c in categories)

    if p_expected >= 1.0:
        return 1.0
    return (p_observed - p_expected) / (1 - p_expected)
