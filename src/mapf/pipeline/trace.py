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

from mapf.core.ports import SamplingParams, Trace, TraceEvent


def _now() -> datetime:
    return datetime.now(UTC)


# One run's trace is a known size. Three agents each record at least one call, so
# fewer than three events cannot be a complete run whatever the file contains.
#
# The ceiling is the arithmetic of a maximal run: intake up to 2 (a degeneration
# retry, ADR 0021), analyst 1, structuralist up to `max_repair_attempts` calls plus
# a `validation_failed` event before each retry. At the configured 3 attempts that
# is 2 + 1 + 3 + 2 = 8. Tripled, so raising a repair budget does not start failing
# healthy runs, and still an order of magnitude below a trace holding a whole band.
MIN_TRACE_EVENTS = 3
MAX_TRACE_EVENTS = 24


def audit_trace(path: Path) -> str | None:
    """Why this file is not one run's audit trail, or `None` if it could be.

    **Existence is not identity.** The failure this exists for wrote every item's
    events into the FIRST item's directory: 56 runs had no trace at all, and the
    one that did held a whole band. A guard checking only that a non-empty file sat
    at the path would have caught the 56 and passed the one that was actually
    wrong — the incident's own worst artifact.

    Per-item wiring fixed that at the source, so this is defence in depth. It is
    still worth having: a guard that would have passed the incident it was written
    for is not a guard. A count is a weak identity check — the strong one is a
    `run_id` inside the events, which the format does not carry — but it is enough
    to separate one run from a band.
    """
    if not path.is_file():
        return "missing"
    if path.stat().st_size == 0:
        return "empty"
    events = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    if events < MIN_TRACE_EVENTS:
        return f"{events} events, fewer than the {MIN_TRACE_EVENTS} a complete run records"
    if events > MAX_TRACE_EVENTS:
        return f"{events} events, more than one run can produce (max {MAX_TRACE_EVENTS})"
    return None


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
        # What actually produced each stage's final response. The agent's own
        # `sampling` property is the CONFIGURED value, which a degeneration retry
        # departs from (ADR 0021) — recording the configured one in that case
        # would put a parameter in the manifest that produced nothing.
        self.sampling: dict[str, SamplingParams] = {}
        self.degeneration_retries: set[str] = set()

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
            if data and data.get("sampling"):
                params = SamplingParams.model_validate(data["sampling"])
                self.sampling[stage] = params
                if params.frequency_penalty is not None:
                    self.degeneration_retries.add(stage)
                    # A degeneration retry REPLACES its first attempt: the looped
                    # output is discarded and the same prompt is re-run, so nothing
                    # downstream ever sees the fragment. The structuralist's repair
                    # loop is the opposite — it feeds the bad response back into the
                    # next prompt — which is why that one stays sticky below.
                    self.truncated_output.discard(stage)
            if data and data.get("finish_reason"):
                reason = str(data["finish_reason"])
                self.finish_reasons[stage] = reason
                # Sticky. Any attempt that was cut off degraded that call, and a
                # later repair attempt does not undo it — the repair prompt is
                # built FROM the truncated response. Only a degeneration retry
                # clears it, above, and only because it discards that response.
                if reason == "length":
                    self.truncated_output.add(stage)
            if data and stage not in self.templates:
                template = str(data.get("template", ""))
                digest = str(data.get("template_sha256", ""))
                if template and digest:
                    name, _, version = template.rpartition(".")
                    self.templates[stage] = (name, version, digest)
        self._inner.record(stage=stage, attempt=attempt, cache_hit=cache_hit, data=data)
