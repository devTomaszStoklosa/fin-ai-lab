import re

from fin_ai_lab.news_classifier.models import LabeledHeadline

_WHITESPACE_RE = re.compile(r"\s+")


def split_chronological(
    headlines: list[LabeledHeadline],
    *,
    train: float = 0.7,
    dev: float = 0.15,
    test: float = 0.15,
) -> tuple[list[LabeledHeadline], list[LabeledHeadline], list[LabeledHeadline]]:
    """REQ-005: chronological split (oldest -> train, newest -> test), with
    near-duplicate headlines removed first so the same story never ends up
    on both sides. "Near-duplicate" here is exact match after normalizing
    whitespace/case — a re-published identical headline; ASSUMPTION, not
    fuzzy text similarity, revisit if a later golden set shows near-dupes
    slipping through uncaught."""
    if abs(train + dev + test - 1.0) > 1e-9:
        raise ValueError("train + dev + test must sum to 1.0")

    ordered = sorted(_dedup(headlines), key=lambda item: item.headline.published_at)

    n = len(ordered)
    train_end = round(n * train)
    dev_end = train_end + round(n * dev)
    return ordered[:train_end], ordered[train_end:dev_end], ordered[dev_end:]


def _dedup(headlines: list[LabeledHeadline]) -> list[LabeledHeadline]:
    seen: set[str] = set()
    deduped: list[LabeledHeadline] = []
    for item in headlines:
        key = normalize_headline_text(item.headline.headline)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def normalize_headline_text(text: str) -> str:
    # Public (not split.py-private) so labeling/progress.py's
    # dedupe_pending_by_text (issue #121) uses the same near-duplicate rule
    # as this module's own split-time dedup, instead of a third,
    # inconsistent normalization.
    return _WHITESPACE_RE.sub(" ", text).strip().lower()
