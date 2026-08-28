"""`runs/<run_id>/trace.jsonl` — the audit trail and Phase 2's input.

Owns the timestamp so that nothing upstream needs a clock. That is not tidiness:
a clock reachable from an agent is a clock that can end up in a prompt, and a
wall-clock value in a prompt destroys the cache (ADR 0001).

Writes and flushes per line rather than buffering. A run that crashes half way
through is exactly the run whose trace you want.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from mapf.core.ports import Trace, TraceEvent


def _now() -> datetime:
    return datetime.now(UTC)


class JsonlTrace:
    """A `Trace` that appends one JSON object per line."""

    def __init__(self, path: Path, *, now: Callable[[], datetime] = _now) -> None:
        self._path = path
        self._now = now
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._path.open("a", encoding="utf-8")

    def record(
        self,
        *,
        stage: str,
        attempt: int = 0,
        cache_hit: bool = False,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        event = TraceEvent(
            at=self._now(), stage=stage, attempt=attempt, cache_hit=cache_hit, data=dict(data or {})
        )
        self._handle.write(event.model_dump_json() + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> JsonlTrace:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class CountingTrace:
    """Counts what happened, then forwards to an inner `Trace`.

    The manifest needs attempts-per-agent and cache-hits-per-agent, and neither is
    recoverable from the artifacts after the fact. Counting here rather than in the
    pipeline means the agents stay unaware they are being measured — they already
    take a `Trace`, so this is a decorator over a Protocol they cannot distinguish.

    Must wrap the trace **before** the agents are constructed, since each agent
    holds its own reference.
    """

    def __init__(self, inner: Trace) -> None:
        self._inner = inner
        self.attempts: dict[str, int] = {}
        self.cache_hits: dict[str, int] = {}
        self.templates: dict[str, tuple[str, str, str]] = {}
        # Summed per stage. Agent 2 runs at temperature 0.7, so reasoning
        # length varies run to run — that variance is worth measuring rather
        # than assuming, and it is invisible unless recorded.
        self.reasoning_tokens: dict[str, int] = {}
        # Why each agent stopped. "length" means the model was cut off mid-output
        # rather than finishing, which produces a truncated fact list or narrative
        # that everything downstream then treats as complete. It has already
        # happened twice unnoticed, so it is counted rather than assumed absent.
        self.finish_reasons: dict[str, str] = {}
        self.truncated_output: set[str] = set()

    def record(
        self,
        *,
        stage: str,
        attempt: int = 0,
        cache_hit: bool = False,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        # Sub-stages like "structuralist.validation_failed" are events, not calls;
        # counting them as attempts would double-count every repair.
        if "." not in stage:
            self.attempts[stage] = max(self.attempts.get(stage, 0), attempt + 1)
            if cache_hit:
                self.cache_hits[stage] = self.cache_hits.get(stage, 0) + 1
            if data and data.get("reasoning_tokens"):
                self.reasoning_tokens[stage] = self.reasoning_tokens.get(stage, 0) + int(
                    data["reasoning_tokens"]
                )
            if data and data.get("finish_reason"):
                reason = str(data["finish_reason"])
                self.finish_reasons[stage] = reason
                if reason == "length":
                    self.truncated_output.add(stage)
            if data and stage not in self.templates:
                template = str(data.get("template", ""))
                digest = str(data.get("template_sha256", ""))
                if template and digest:
                    name, _, version = template.rpartition(".")
                    self.templates[stage] = (name, version, digest)
        self._inner.record(stage=stage, attempt=attempt, cache_hit=cache_hit, data=data)
