import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from fin_ai_lab.filings_rag.index.store import VectorStore
from fin_ai_lab.filings_rag.models import Chunk

# Gitignored (data/index/): GPW chunks are text from the owner's private
# PDFs in data/private/gpw/.
INDEX_PATH = Path("data/index/filings_rag/index.npz")


class SavedIndex(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    store: VectorStore
    # The query must be embedded with the same model as the chunks were —
    # vectors from two different models aren't comparable.
    embedding_model: str
    built_at: datetime


def save_index(
    store: VectorStore, *, embedding_model: str, built_at: datetime, path: Path = INDEX_PATH
) -> None:
    """One file holding chunks, vectors and metadata together, so a reader
    never pairs the chunks of one build with the vectors of another.
    Written to a temporary file first and swapped in with os.replace — a
    reader (the web app, #225) never sees a half-written index."""
    vectors = store.vectors
    if vectors is None:
        raise ValueError("Refusing to save an empty index")

    chunks_json = json.dumps([chunk.model_dump() for chunk in store.chunks], ensure_ascii=False)
    meta_json = json.dumps({"embedding_model": embedding_model, "built_at": built_at.isoformat()})

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    # A file object, not a path: np.savez appends ".npz" to a path that
    # doesn't already end with it, which would break the rename below.
    with tmp_path.open("wb") as file:
        np.savez_compressed(
            file,
            # float32 halves the file size; the precision lost is far below
            # anything that changes a cosine-similarity ranking.
            vectors=vectors.astype(np.float32),
            chunks=_utf8_array(chunks_json),
            meta=_utf8_array(meta_json),
        )
    os.replace(tmp_path, path)


def load_index(path: Path = INDEX_PATH) -> SavedIndex | None:
    if not path.exists():
        return None

    with np.load(path, allow_pickle=False) as data:
        vectors = data["vectors"]
        chunks = [Chunk(**raw) for raw in json.loads(_utf8_text(data["chunks"]))]
        meta = json.loads(_utf8_text(data["meta"]))

    store = VectorStore()
    store.add(chunks, vectors)
    return SavedIndex(
        store=store,
        embedding_model=meta["embedding_model"],
        built_at=datetime.fromisoformat(meta["built_at"]),
    )


def _utf8_array(text: str) -> np.ndarray:
    # Raw UTF-8 bytes, not a numpy unicode string, which stores 4 bytes per
    # character.
    return np.frombuffer(text.encode("utf-8"), dtype=np.uint8)


def _utf8_text(array: np.ndarray) -> str:
    return array.tobytes().decode("utf-8")
