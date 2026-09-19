import re
from datetime import date, timedelta
from pathlib import Path

from fin_ai_lab.investment_committee.models import Thesis
from fin_ai_lab.portfolio_xray.canonical import Portfolio

# Open question #4 (03-design.md): append-only JSONL per portfolio, not a
# snapshot like market_pulse/state.py — REQ-011 needs history across many
# runs (Brier score), which an overwrite-per-run file would destroy.
THESES_DIR = Path("data/memory/investment_committee")

# ASSUMPTION: 01-story.md/02-spec.md only ever give "1 month" / "1 year"
# style examples, never a full grammar — this covers day/week/month/year,
# singular or plural, English or Polish. An unparseable horizon means "we
# don't know when this resolves", so reckon_theses leaves it alone rather
# than guessing.
_HORIZON_RE = re.compile(
    r"(\d+)\s*(day|week|month|year|dzień|dni|tydzień|tygodni|miesiąc|miesięcy|rok|lat)",
    re.IGNORECASE,
)
_UNIT_DAYS = {
    "day": 1, "dzień": 1, "dni": 1,
    "week": 7, "tydzień": 7, "tygodni": 7,
    "month": 30, "miesiąc": 30, "miesięcy": 30,
    "year": 365, "rok": 365, "lat": 365,
}


def _slug(portfolio_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", portfolio_id).strip("_")


def _path(portfolio_id: str, directory: Path) -> Path:
    return directory / f"{_slug(portfolio_id)}.jsonl"


def append_theses(portfolio_id: str, theses: list[Thesis], directory: Path = THESES_DIR) -> None:
    if not theses:
        return
    path = _path(portfolio_id, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for thesis in theses:
            f.write(thesis.model_dump_json() + "\n")


def load_theses(portfolio_id: str, directory: Path = THESES_DIR) -> list[Thesis]:
    path = _path(portfolio_id, directory)
    if not path.exists():
        return []
    return [
        Thesis.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def reckon_theses(previous_theses: list[Thesis], current_portfolio: Portfolio) -> list[Thesis]:
    """P5-S5, REQ-010: pure function, no LLM call. It only fills in the
    mechanical half of reckoning — whether a thesis's own horizon has
    elapsed yet (02-spec.md's edge case: horizon longer than the elapsed
    time stays "not_yet_resolvable", never forced to an early verdict).
    Whether an elapsed thesis actually came true is a real-world judgment
    this function does not make: it leaves `outcome` as None for those,
    rather than guess "accurate"/"inaccurate" from a portfolio snapshot
    alone. Already-resolved theses (set by whatever later process makes
    that judgment) pass through unchanged."""
    reckoned = []
    for thesis in previous_theses:
        if thesis.outcome is not None:
            reckoned.append(thesis)
            continue

        due_date = _resolution_date(thesis)
        if due_date is None or current_portfolio.valuation_date < due_date:
            reckoned.append(thesis.model_copy(update={"outcome": "not_yet_resolvable"}))
        else:
            reckoned.append(thesis)  # horizon elapsed, but truth-judgment isn't implemented here
    return reckoned


def _resolution_date(thesis: Thesis) -> date | None:
    match = _HORIZON_RE.search(thesis.horizon)
    if not match:
        return None
    count, unit = int(match.group(1)), match.group(2).lower()
    return thesis.made_at + timedelta(days=count * _UNIT_DAYS[unit])
