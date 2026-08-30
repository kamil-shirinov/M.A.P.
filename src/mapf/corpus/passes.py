"""Pass boundaries for the two-pass ambiguous band (ADR 0019 §1).

The ambiguous band is executed in halves so the ten-night outcome stays available
as an option on *time*, decided without inspecting any score. That rule was
pre-committed; this module is what stops it being a note in a document.

**Passes interleave rather than partition the calendar.** Taking the first half of
the plan and calling it pass one would make it a calendar-contiguous subsample —
roughly H1 of the band — so stopping after it would confound "we stopped early"
with "we only measured the first half of the year", and the leakage estimate would
carry a seasonal bias nobody chose. Assigning by position modulo the pass count
makes every pass a spread sample of the whole band, so an early stop costs
precision and nothing else.

The assignment is a pure function of the frozen plan order, so it needs no seed and
no record: the same corpus yields the same passes on any machine, forever.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from mapf.core.errors import MapError
from mapf.corpus.ledger import Ledger, is_terminal
from mapf.corpus.runner import CorpusItem


class IncompletePassError(MapError):
    """Scoring was attempted before every declared pass finished.

    The refusal is the point. A leakage estimate computed on a half-finished band
    is not a preliminary version of the real number — it is a different number, and
    reporting it would be the data-dependent stopping the two-pass design exists to
    prevent (ADR 0019 §2).
    """

    def __init__(self, missing: Sequence[str], detail: str) -> None:
        self.missing = tuple(missing)
        super().__init__(
            f"cannot score: {', '.join(missing)} incomplete — {detail}. "
            "Finish the pass, or record the decision to stop and score only the "
            "passes that were declared complete."
        )


@dataclass(frozen=True)
class Pass:
    """One executable slice of a band."""

    label: str
    index: int
    of: int
    items: tuple[CorpusItem, ...]

    @property
    def size(self) -> int:
        return len(self.items)


@dataclass(frozen=True)
class PassStatus:
    label: str
    total: int
    complete: int
    terminal: int

    @property
    def resolved(self) -> int:
        """Items that will never be attempted again, either way."""
        return self.complete + self.terminal

    @property
    def finished(self) -> bool:
        return self.resolved >= self.total

    @property
    def remaining(self) -> int:
        return max(self.total - self.resolved, 0)


def split_passes(items: Sequence[CorpusItem], *, band: str, count: int = 2) -> tuple[Pass, ...]:
    """Partition a band's items into `count` interleaved passes.

    `items` must already be in the deterministic plan order; the assignment is
    positional, so a different order would produce different passes.
    """
    if count < 1:
        raise ValueError(f"count must be at least 1, got {count}")
    buckets: list[list[CorpusItem]] = [[] for _ in range(count)]
    for position, item in enumerate(items):
        buckets[position % count].append(item)
    return tuple(
        Pass(
            label=f"{band}_half_{i + 1}" if count == 2 else f"{band}_pass_{i + 1}",
            index=i,
            of=count,
            items=tuple(bucket),
        )
        for i, bucket in enumerate(buckets)
    )


def status_of(pass_: Pass, ledger: Ledger) -> PassStatus:
    """How far one pass got, read from the ledger alone.

    Deliberately counts only what the ledger says. Asking the filesystem how many
    run directories exist would count a crash between artifact writes as a finished
    item — the defect the ledger exists to rule out.
    """
    resolved = ledger.resolved()
    complete = terminal = 0
    for item in pass_.items:
        entry = resolved.get(item.key)
        if entry is None:
            continue
        if entry.status == "complete":
            complete += 1
        elif is_terminal(entry.reason):
            terminal += 1
    return PassStatus(label=pass_.label, total=pass_.size, complete=complete, terminal=terminal)


def require_finished(
    passes: Sequence[Pass], ledger: Ledger, *, declared: Sequence[str] | None = None
) -> tuple[PassStatus, ...]:
    """Raise unless every declared pass has finished. Returns their statuses.

    `declared` names the passes that were actually meant to run. Stopping after the
    first half is a legitimate outcome of the continuation rule — but it has to be
    *declared*, so that "we chose to stop" is distinguishable in the record from
    "it never finished".
    """
    statuses = tuple(status_of(p, ledger) for p in passes)
    wanted = set(declared) if declared is not None else {p.label for p in passes}
    unfinished = [s for s in statuses if s.label in wanted and not s.finished]
    if unfinished:
        raise IncompletePassError(
            [s.label for s in unfinished],
            "; ".join(
                f"{s.label}: {s.resolved}/{s.total} resolved, {s.remaining} outstanding"
                for s in unfinished
            ),
        )
    return statuses


def elapsed_report(passes: Sequence[Pass], ledger: Ledger) -> dict[str, float]:
    """Wall-clock seconds recorded per pass.

    The *only* quantity the continuation decision is allowed to read. It contains
    no outcome, which is what keeps the decision independent of the data.
    """
    resolved = ledger.resolved()
    out: dict[str, float] = {}
    for pass_ in passes:
        # float() because sum() over an empty generator returns int, which would
        # quietly violate the declared return type for an untouched pass.
        out[pass_.label] = float(
            sum(
                entry.elapsed_s
                for item in pass_.items
                if (entry := resolved.get(item.key)) is not None
            )
        )
    return out
