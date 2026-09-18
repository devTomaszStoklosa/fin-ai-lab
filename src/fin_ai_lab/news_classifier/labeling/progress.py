import hashlib
import json
from pathlib import Path

from fin_ai_lab.news_classifier.models import Headline

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
