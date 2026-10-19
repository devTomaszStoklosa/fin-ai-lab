"""P4's public surface for other projects (docs/ARCHITECTURE.md rule 6):
the web app's "Porównanie modeli" tab imports these names from here, never
from P4's internal modules."""

from fin_ai_lab.news_classifier.corpus_store import CORPUS_PATH, load_labeled

__all__ = ["CORPUS_PATH", "load_labeled"]
