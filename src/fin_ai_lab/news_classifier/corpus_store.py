from pathlib import Path

from fin_ai_lab.news_classifier.models import LabeledHeadline

# Gitignored — accumulated over repeated labeling runs (labeling/teacher.py
# + labeling/progress.py), not a fixture.
CORPUS_PATH = Path("data/corpus/news_classifier/labeled.jsonl")


def append_labeled(items: list[LabeledHeadline], path: Path = CORPUS_PATH) -> None:
    if not items:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for item in items:
            f.write(item.model_dump_json() + "\n")


def load_labeled(path: Path = CORPUS_PATH) -> list[LabeledHeadline]:
    if not path.exists():
        return []
    return [
        LabeledHeadline.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
