"""The run ledger — what makes a twelve-night job resumable.

`new_run_id` is a uuid4, so nothing about a run directory says which corpus item
produced it, and `execute` writes `forecast.json`, then `manifest.json`, then
optionally a chart. A resume that scanned `runs/` would therefore both fail to find
completed items and mistake a crash between those writes for a finished one.

So completion is recorded explicitly, appended **only after every artifact for an
item has landed**, keyed by the item rather than by the run. An entry in this file
is a promise that the artifacts exist; the absence of one is never evidence that
work was not done, only that it was not *finished*.

JSON Lines rather than a single document: an append is one `write` of one line, so
a process killed mid-append corrupts at most the final line, and a reader can skip
it. Rewriting a whole JSON array on every item would risk the entire history.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field

from mapf.core.models import DomainModel, Ticker

Status = Literal["complete", "failed"]

# Failure reasons are typed so the ledger can distinguish one provider failing,
# one band failing or one ticker failing from genuinely scattered noise (ADR 0019).
FailureReason = Literal[
    "inference_unreachable",
    "inference_timeout",
    "budget_exhausted",
    "market_data",
    "repair_exhausted",
    "no_material_facts",
    "missing_exhibit",
    "context_overflow",
    "output_truncated",
    "missing_artifact",
    "other",
]

# The split that decides what a resume retries.
#
# A transient failure is one a later attempt could plausibly survive: the server
# was down, the socket timed out, a scraper throttled. Those are left absent from
# the completed set so the next pass picks them up.
#
# A terminal failure is a property of the item, not of the moment. A filing with
# no Exhibit 99.1 has no exhibit on the next pass either. Retrying it every resume
# would consume the failure threshold afresh each time and eventually halt the run
# on an item that can never succeed — so it is recorded as done, with its failure
# preserved, and never attempted again.
TERMINAL_REASONS: frozenset[str] = frozenset(
    {
        "missing_exhibit",
        "repair_exhausted",
        "no_material_facts",
        "context_overflow",
        "output_truncated",
        "missing_artifact",
    }
)

# `budget_exhausted` is deliberately NOT terminal. The analyst samples at
# temperature 0.7, so a second attempt genuinely explores a different reasoning
# path and may finish inside the budget. The same reason would be terminal for a
# temperature-0 agent, which is why the distinction is about the sampling rather
# than about the exception.


def is_terminal(reason: FailureReason | None) -> bool:
    return reason in TERMINAL_REASONS


class LedgerEntry(DomainModel):
    """One corpus item, terminal. Never written for work still in progress."""

    ticker: Ticker
    band: str = Field(min_length=1)
    filing_date: date
    status: Status
    run_id: UUID | None = None
    reason: FailureReason | None = None
    detail: str = ""
    elapsed_s: float = Field(default=0.0, ge=0.0)

    # Health, not score (ADR 0019 §7). These say whether the machine is working.
    unparseable: int = Field(default=0, ge=0)
    divergent: int = Field(default=0, ge=0)
    ungrounded_numerals: int = Field(default=0, ge=0)
    degenerate_spread: bool = False
    reasoning_tokens: int = Field(default=0, ge=0)
    cache_hits: int = Field(default=0, ge=0)

    # Whether the ADR 0020 truncation rule bit on this item, and by how much. The
    # exhibit's frozen hash still covers the FULL document EDGAR served; this is
    # the processing step recorded beside it, never folded into it.
    truncated: bool = False
    elided_chars: int = Field(default=0, ge=0)

    # The other truncation: an agent that stopped at its token cap rather than
    # finishing, so the fact list or narrative it passed on is a fragment. Recorded
    # in the same shape, because it degrades a forecast the same silent way — the
    # result is schema-valid and built on half a summary.
    output_truncated: bool = False
    truncated_agents: str = ""

    @property
    def key(self) -> tuple[str, str, date]:
        return (self.ticker, self.band, self.filing_date)


class Ledger:
    """Append-only record of terminal item outcomes."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def append(self, entry: LedgerEntry) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json() + "\n")

    def entries(self) -> Iterator[LedgerEntry]:
        """Every readable entry, oldest first.

        A truncated final line — a process killed mid-append — is skipped rather
        than raised on. Losing the last item to a re-run costs one forecast;
        refusing to load the ledger costs the whole resume.
        """
        if not self._path.is_file():
            return
        for line in self._path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield LedgerEntry.model_validate_json(stripped)
            except (ValueError, json.JSONDecodeError):
                continue

    def completed(self) -> set[tuple[str, str, date]]:
        """Items a resume must not attempt again.

        A *transient* failure is deliberately absent, so the next pass retries it
        and an outage costs minutes rather than the run. A *terminal* failure is
        present, because it would fail identically on every resume — retrying it
        would consume the failure threshold each pass and eventually halt the run
        on an item that can never succeed.
        """
        return {
            e.key
            for e in self.entries()
            if e.status == "complete" or is_terminal(e.reason)
        }

    def resolved(self) -> dict[tuple[str, str, date], LedgerEntry]:
        """Every item with a terminal outcome, latest entry winning."""
        out: dict[tuple[str, str, date], LedgerEntry] = {}
        for entry in self.entries():
            if entry.status == "complete" or is_terminal(entry.reason):
                out[entry.key] = entry
        return out
