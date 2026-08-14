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
    "other",
]


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
        """Items a resume must skip. Failures are deliberately absent: a failed
        item is retried on the next pass, which is what makes a transient outage
        cost minutes rather than the run."""
        return {e.key for e in self.entries() if e.status == "complete"}
