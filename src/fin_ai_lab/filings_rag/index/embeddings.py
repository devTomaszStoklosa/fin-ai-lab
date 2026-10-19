import hashlib
import json
from pathlib import Path

from fin_ai_lab.core.llm.embeddings import EmbeddingClient

CACHE_DIR = Path("data/cache/embeddings")


async def embed_with_cache(
    texts: list[str],
    *,
    model: str,
    embedding_client: EmbeddingClient,
    cache_dir: Path = CACHE_DIR,
) -> list[list[float]]:
    """Embeds each text once; a cache hit for unchanged text never pays
    twice. Cache is keyed by (model, text hash) via the model-named
    subdirectory, so switching models invalidates the cache automatically —
    03-design.md's "index.embeddings" contract."""
    model_cache_dir = cache_dir / model
    model_cache_dir.mkdir(parents=True, exist_ok=True)

    vectors: list[list[float] | None] = [None] * len(texts)
    to_fetch_indices: list[int] = []
    to_fetch_texts: list[str] = []

    for index, text in enumerate(texts):
        cache_path = model_cache_dir / f"{_cache_key(text)}.json"
        if cache_path.exists():
            vectors[index] = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            to_fetch_indices.append(index)
            to_fetch_texts.append(text)

    if to_fetch_texts:
        result = await embedding_client.embed(to_fetch_texts, model=model)
        for fetch_position, chunk_index in enumerate(to_fetch_indices):
            vector = result.vectors[fetch_position]
            vectors[chunk_index] = vector
            cache_path = model_cache_dir / f"{_cache_key(texts[chunk_index])}.json"
            cache_path.write_text(json.dumps(vector), encoding="utf-8")

    missing = [index for index, vector in enumerate(vectors) if vector is None]
    if missing:
        raise ValueError(f"Embedding client returned fewer vectors than requested: {missing}")
    return vectors


def _cache_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
