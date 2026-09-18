import csv
import random
from pathlib import Path
from typing import TypedDict

from fin_ai_lab.news_classifier.labeling.calibration import cohens_kappa
from fin_ai_lab.news_classifier.models import LabeledHeadline

# REQ-011 / docs/EVALS.md "Kalibracja LLM-as-judge": the human rates blind,
# before seeing the model's answer, then agreement is computed — never the
# reverse. The exported CSV therefore carries no teacher label column at
# all, only empty ones for the human to fill; showing the teacher's answer
# next to the field to fill in would anchor the human's judgment and
# inflate kappa artificially.
HUMAN_FIELDS = ["human_sentiment", "human_event_type", "human_tickers"]
_FIELDNAMES = ["headline", "lead", "source", "published_at", *HUMAN_FIELDS]

# 01-story.md open question #2 (owner's answer): 300-500 — this is the
# upper end, used as a default, not a requirement to review exactly this
# many. A sample larger than the corpus just reviews the whole corpus.
DEFAULT_SAMPLE_SIZE = 500
# Fixed, not random-per-run: re-exporting (e.g. after the corpus grows)
# should draw a reproducible sample, not silently ask the owner to
# re-review a different set of headlines each time.
SAMPLE_SEED = 42


def export_for_review(
    labeled: list[LabeledHeadline],
    path: Path,
    *,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
) -> list[LabeledHeadline]:
    """Writes a blind-review CSV (see HUMAN_FIELDS docstring above) and
    returns the sampled subset, so the caller can report how many
    headlines were exported without re-reading the file."""
    sample = _sample(labeled, sample_size)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
        writer.writeheader()
        for item in sample:
            writer.writerow(
                {
                    "headline": item.headline.headline,
                    "lead": item.headline.lead or "",
                    "source": item.headline.source,
                    "published_at": item.headline.published_at.isoformat(),
                    "human_sentiment": "",
                    "human_event_type": "",
                    "human_tickers": "",
                }
            )
    return sample


class _HumanRow(TypedDict):
    sentiment: str
    event_type: str
    tickers: list[str]


def _read_reviewed_rows(path: Path) -> dict[str, _HumanRow]:
    """Keyed by headline text (unique within one export — the corpus has
    no duplicate headlines after split.py's dedup) — skips rows the human
    left blank, since a partially-worked-through export is expected, not
    an error."""
    reviewed: dict[str, _HumanRow] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sentiment = row["human_sentiment"].strip()
            event_type = row["human_event_type"].strip()
            if not sentiment or not event_type:
                continue
            tickers = [t.strip() for t in row["human_tickers"].split(",") if t.strip()]
            reviewed[row["headline"]] = _HumanRow(
                sentiment=sentiment, event_type=event_type, tickers=tickers
            )
    return reviewed


class CalibrationReport(TypedDict):
    n_reviewed: int
    n_exported: int
    sentiment_kappa: float
    event_type_kappa: float
    tickers_exact_match_pct: float


def score_calibration(sample: list[LabeledHeadline], reviewed_path: Path) -> CalibrationReport:
    """REQ-011: compares the exported sample's teacher labels against the
    human's blind review. Rows the human left blank are excluded, not
    treated as disagreement — an unreviewed row carries no signal either
    way (docs/EVALS.md calibration methodology, ≥0.6 kappa bar)."""
    reviewed = _read_reviewed_rows(reviewed_path)
    # The corpus isn't deduped by headline text (dedup happens later, at
    # split time — 03-design.md) — a headline crossposted to two feeds
    # (e.g. bankier + bankier-wiadomosci) can appear twice with the same
    # text. Matching by text would otherwise count one human judgment
    # twice, double-weighting it in the kappa calculation below.
    seen_texts: set[str] = set()
    matched: list[LabeledHeadline] = []
    for item in sample:
        text = item.headline.headline
        if text in reviewed and text not in seen_texts:
            matched.append(item)
            seen_texts.add(text)
    if not matched:
        raise ValueError(f"No reviewed rows found in {reviewed_path} — fill in at least one row")

    human_sentiments = [reviewed[item.headline.headline]["sentiment"] for item in matched]
    human_event_types = [reviewed[item.headline.headline]["event_type"] for item in matched]
    human_tickers = [reviewed[item.headline.headline]["tickers"] for item in matched]

    teacher_sentiments = [item.label.sentiment for item in matched]
    teacher_event_types = [item.label.event_type for item in matched]
    teacher_tickers = [item.label.tickers for item in matched]

    exact_ticker_matches = sum(
        1 for a, b in zip(teacher_tickers, human_tickers, strict=True) if set(a) == set(b)
    )

    return CalibrationReport(
        n_reviewed=len(matched),
        n_exported=len(sample),
        sentiment_kappa=cohens_kappa(teacher_sentiments, human_sentiments),
        event_type_kappa=cohens_kappa(teacher_event_types, human_event_types),
        tickers_exact_match_pct=exact_ticker_matches / len(matched),
    )


def _sample(labeled: list[LabeledHeadline], sample_size: int) -> list[LabeledHeadline]:
    if sample_size >= len(labeled):
        return list(labeled)
    return random.Random(SAMPLE_SEED).sample(labeled, sample_size)
