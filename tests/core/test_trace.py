import json
from datetime import UTC, datetime
from pathlib import Path

from fin_ai_lab.core.llm.trace import TraceSink, TraceSpan


def test_write_appends_span_to_dated_jsonl_file(tmp_path: Path) -> None:
    sink = TraceSink(traces_dir=tmp_path)
    span = TraceSpan(
        trace_id="t1",
        span_id="s1",
        ts=datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC),
        kind="llm",
        name="complete",
        model="gemini-2.5-flash",
    )

    sink.write(span)

    lines = (tmp_path / "2026-09-15.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["trace_id"] == "t1"


def test_write_appends_second_span_on_same_day(tmp_path: Path) -> None:
    sink = TraceSink(traces_dir=tmp_path)
    ts = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)

    sink.write(TraceSpan(trace_id="t1", span_id="s1", ts=ts, kind="llm", name="complete"))
    sink.write(TraceSpan(trace_id="t2", span_id="s2", ts=ts, kind="llm", name="complete"))

    lines = (tmp_path / "2026-09-15.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
