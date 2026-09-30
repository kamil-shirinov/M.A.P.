"""`started_at`: when a run was made, read off the head of its own trace.

The anchor is not that time. A run made before a session settles opens from the
previous close, so a journal that printed only the anchor put the run on the day
before it happened. The trace's first event is stamped by the run's clock as it
happened, and it is the first key of the first line, so reading the file's head
is enough — which matters, because that line carries a whole filing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mapf.pipeline.trace import JsonlTrace, started_at

MADE = datetime(2026, 9, 30, 12, 21, 11, 511037, tzinfo=UTC)


def test_it_is_the_first_events_time(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    clock = iter([MADE, datetime(2026, 9, 30, 12, 25, tzinfo=UTC)])
    trace = JsonlTrace(path, now=lambda: next(clock))
    trace.record(stage="intake")
    trace.record(stage="analyst")
    trace.close()
    assert started_at(path) == MADE


def test_a_first_record_carrying_a_whole_filing_is_not_read_to_find_it(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    trace = JsonlTrace(path, now=lambda: MADE)
    trace.record(stage="intake", data={"messages": ["x" * 2_000_000]})
    trace.close()
    assert started_at(path) == MADE


def test_an_unknown_time_is_none_never_a_guess(tmp_path: Path) -> None:
    assert started_at(tmp_path / "missing.jsonl") is None
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert started_at(empty) is None
    other = tmp_path / "other.jsonl"
    other.write_text('{"stage":"intake","at":"2026-09-30T12:21:11Z"}\n', encoding="utf-8")
    assert started_at(other) is None, "a trace that does not open with its time"
    garbled = tmp_path / "garbled.jsonl"
    garbled.write_text('{"at":"the thirtieth"}\n', encoding="utf-8")
    assert started_at(garbled) is None
