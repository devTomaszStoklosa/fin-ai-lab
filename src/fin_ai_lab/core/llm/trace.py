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
