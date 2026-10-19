import json
from datetime import UTC, datetime
from pathlib import Path

from fin_ai_lab.core.llm.trace import TraceSink, TraceSpan, count_calls_today


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


def _today_sink(tmp_path: Path) -> TraceSink:
    return TraceSink(traces_dir=tmp_path)


def test_count_calls_today_counts_llm_spans_per_model(tmp_path: Path) -> None:
    sink = _today_sink(tmp_path)
    now = datetime.now(UTC)

    def span(trace_id: str, kind: str, model: str | None = None) -> TraceSpan:
        return TraceSpan(
            trace_id=trace_id, span_id=trace_id, ts=now, kind=kind, name="x", model=model
        )

    sink.write(span("t1", "llm", "gemini-3.6-flash"))
    sink.write(span("t2", "llm", "gemini-3.6-flash"))
    sink.write(span("t3", "llm", "gemini-embedding-2"))
    # Not an LLM call -- must not be counted alongside them.
    sink.write(span("t4", "http"))

    counts = count_calls_today(traces_dir=tmp_path)

    assert counts == {"gemini-3.6-flash": 2, "gemini-embedding-2": 1}


def test_count_calls_today_counts_a_failed_call_too(tmp_path: Path) -> None:
    sink = _today_sink(tmp_path)
    now = datetime.now(UTC)
    sink.write(
        TraceSpan(
            trace_id="t1",
            span_id="s1",
            ts=now,
            kind="llm",
            name="complete",
            model="gemini-3.6-flash",
            error="ServerError: 503",
        )
    )

    counts = count_calls_today(traces_dir=tmp_path)

    assert counts == {"gemini-3.6-flash": 1}


def test_count_calls_today_returns_empty_dict_without_a_file(tmp_path: Path) -> None:
    assert count_calls_today(traces_dir=tmp_path) == {}


def test_count_calls_today_counts_every_http_attempt_of_a_call(tmp_path: Path) -> None:
    # #254: a retried call sent two requests, and Gemini's quota counted both.
    sink = _today_sink(tmp_path)
    now = datetime.now(UTC)
    sink.write(
        TraceSpan(
            trace_id="t1",
            span_id="s1",
            ts=now,
            kind="llm",
            name="complete",
            model="gemini-3.6-flash",
            attempts=2,
        )
    )
    # Older span, written before `attempts` existed -- counts as one request.
    sink.write(
        TraceSpan(
            trace_id="t2",
            span_id="s2",
            ts=now,
            kind="llm",
            name="complete",
            model="gemini-3.6-flash",
        )
    )

    counts = count_calls_today(traces_dir=tmp_path)

    assert counts == {"gemini-3.6-flash": 3}
