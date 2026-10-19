import hashlib
import json
from pathlib import Path

CACHE_DIR = Path("data/cache/evals")


def cache_key(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EvalCache:
    def __init__(self, cache_dir: Path = CACHE_DIR) -> None:
        self._cache_dir = cache_dir

    def get(self, namespace: str, key: str) -> dict | None:
        path = self._path(namespace, key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def set(self, namespace: str, key: str, value: dict) -> None:
        path = self._path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def _path(self, namespace: str, key: str) -> Path:
        return self._cache_dir / namespace / f"{key}.json"
