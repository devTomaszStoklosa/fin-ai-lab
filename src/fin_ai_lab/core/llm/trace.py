import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

TRACES_DIR = Path("traces")


class TraceSpan(BaseModel):
    trace_id: str
    span_id: str
    ts: datetime
    kind: str
    name: str
    model: str | None = None
    prompt_id: str | None = None
    prompt_version: int | None = None
    usage: dict[str, int] | None = None
    cost_usd: Decimal | None = None
    latency_ms: int | None = None
    # HTTP requests sent for this one call -- more than 1 when the SDK
    # retried or ran several automatic-function-calling turns (#254).
    # None for clients that don't track it (Groq), and in older traces.
    attempts: int | None = None
    error: str | None = None


class TraceSink:
    def __init__(self, traces_dir: Path = TRACES_DIR) -> None:
        self._traces_dir = traces_dir

    def write(self, span: TraceSpan) -> None:
        self._traces_dir.mkdir(parents=True, exist_ok=True)
        file_name = span.ts.astimezone(UTC).strftime("%Y-%m-%d") + ".jsonl"
        path = self._traces_dir / file_name
        with path.open("a", encoding="utf-8") as f:
            f.write(span.model_dump_json() + "\n")


def count_calls_today(traces_dir: Path = TRACES_DIR) -> dict[str, int]:
    """Today's requests per model, from `kind="llm"` spans -- a failed call
    still counts (it consumed an attempt against the provider's quota,
    whether or not it succeeded), and a call that sent several HTTP
    requests counts each of them (`attempts`, #254), since the provider's
    quota does. Spans without `attempts` count as 1. Used to show usage
    against the free tier's daily cap (docs/LLM-API.md) without a live
    provider call of its own."""
    path = traces_dir / (datetime.now(UTC).strftime("%Y-%m-%d") + ".jsonl")
    if not path.exists():
        return {}

    counts: Counter[str] = Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        span = json.loads(line)
        if span.get("kind") == "llm" and span.get("model"):
            counts[span["model"]] += span.get("attempts") or 1
    return dict(counts)
