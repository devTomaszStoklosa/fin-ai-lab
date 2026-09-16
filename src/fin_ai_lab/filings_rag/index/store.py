import numpy as np

from fin_ai_lab.filings_rag.models import Chunk


class VectorStore:
    """Full in-memory cosine search over numpy arrays — no vector engine
    (FAISS etc.) needed at this corpus scale (03-design.md Option D, and
    docs/ENVIRONMENT.md already flags FAISS as an AVX2 risk)."""

    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._vectors: np.ndarray | None = None

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        if not chunks:
            return

        matrix = np.array(vectors, dtype=float)
        self._vectors = matrix if self._vectors is None else np.vstack([self._vectors, matrix])
        self._chunks.extend(chunks)

    def search(self, query_vector: list[float], *, top_k: int) -> list[tuple[Chunk, float]]:
        if self._vectors is None or not self._chunks:
            return []

        scores = _cosine_similarity(self._vectors, np.array(query_vector, dtype=float))
        top_indices = np.argsort(-scores)[:top_k]
        return [(self._chunks[i], float(scores[i])) for i in top_indices]

    def has_company(self, company: str) -> bool:
        return any(chunk.company == company for chunk in self._chunks)

    def __len__(self) -> int:
        return len(self._chunks)


def _cosine_similarity(matrix: np.ndarray, query: np.ndarray) -> np.ndarray:
    matrix_norms = np.linalg.norm(matrix, axis=1)
    query_norm = np.linalg.norm(query)
    denominator = matrix_norms * query_norm
    denominator[denominator == 0] = np.finfo(float).eps
    return (matrix @ query) / denominator
