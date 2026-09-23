import hashlib
import json
from pathlib import Path

from fin_ai_lab.news_classifier.models import Headline
from fin_ai_lab.news_classifier.split import normalize_headline_text

# Gitignored (data/state/), same convention as market_pulse/state.py —
# tracks which headlines the teacher already labeled, so a repeated run
# (max_calls per day, no Batch API — 03-design.md) never re-pays for one.
STATE_PATH = Path("data/state/news_classifier_labeled.json")


def headline_key(headline: Headline) -> str:
    payload = f"{headline.source}|{headline.headline}|{headline.published_at.isoformat()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_labeled_keys(path: Path = STATE_PATH) -> set[str]:
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def save_labeled_keys(keys: set[str], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(keys)), encoding="utf-8")


def unlabeled(headlines: list[Headline], already_labeled: set[str]) -> list[Headline]:
    return [h for h in headlines if headline_key(h) not in already_labeled]


def dedupe_pending_by_text(headlines: list[Headline]) -> list[Headline]:
    """Two RSS feeds can cross-post the same real-world story under
    different `source` values (issue #121 — bankier's two categories are
    the observed case). headline_key()'s (source, headline, published_at)
    hash treats those as distinct, so both would otherwise reach the
    teacher and waste a call on a duplicate. Keeps the first occurrence
    (feed-fetch order) per normalized text.

    Deliberately not folded into headline_key() itself: that hash is
    persisted (STATE_PATH) and already holds real accumulated progress —
    changing its shape would invalidate every already-labeled entry and
    re-send them all to the teacher on the next run, the opposite of what
    this fix is for. This only dedupes within one collection run, which is
    what the real cross-source duplicates observed so far look like."""
    seen: set[str] = set()
    deduped: list[Headline] = []
    for headline in headlines:
        key = normalize_headline_text(headline.headline)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(headline)
    return deduped
