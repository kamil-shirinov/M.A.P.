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
    "exhibit_error",
    "exhibit_unreachable",
    "context_overflow",
    "output_truncated",
    "missing_artifact",
    "request_rejected",
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
        # A 4xx says the request itself is unacceptable to this server, so an
        # identical retry produces an identical refusal. That is protocol
        # semantics rather than a guess about one vendor's wording, which is what
        # lets this be classified without reading the body (ADR 0022).
        "request_rejected",
    }
)

# `budget_exhausted` is NOT in the terminal set, and the reason it is not has been
# corrected. It used to read: "the analyst samples at temperature 0.7, so a second
# attempt genuinely explores a different reasoning path." That is not what happens.
# `seed` is fixed for the analyst and goes on every request, and `attempt` reaches
# the cache key but never the request body — so a retry sends a BYTE-IDENTICAL
# request, and whether it explores anything depends entirely on the backend choosing
# not to honour the seed. Finding #24 measured this backend as only partially
# deterministic, which makes that a coin-flip nobody chose, in the direction where
# being wrong costs a full analyst call on every resume.
#
# It stays non-terminal because a long reasoning chain genuinely can be a one-off.
# What bounds it is no longer an assumption about sampling but the repeat rule below:
# the first failure buys a retry, and a second identical outcome is the answer.


# --------------------------------------------------------------------------
# The repeat rule (ADR 0024)
# --------------------------------------------------------------------------
# "Transient" is a hypothesis about an ITEM, and the ledger already holds the
# evidence to test it. A reason that recurs on the same item twice has stopped being
# a hypothesis, so the item is resolved rather than retried on every resume — which
# would otherwise consume the failure allowance afresh each pass and halt the run on
# something that can never succeed. That is the `missing_exhibit` shape arriving
# through a reason nobody classified as terminal.
REPEAT_LIMIT = 2

# Reasons where a repeat says nothing about the item, because the cause is shared
# infrastructure rather than the item itself. Five items failed together when DNS
# dropped; a second outage spanning two resumes would burn all five permanently, and
# the failure they share is the afternoon, not the filing.
ALWAYS_RETRIED: frozenset[str] = frozenset(
    {
        "inference_unreachable",
        "inference_timeout",
        "market_data",
        "exhibit_unreachable",
    }
)


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

    # Whether an agent looped at its cap and was re-run once under a frequency
    # penalty (ADR 0021). These items were produced under different sampling from
    # the rest of the corpus, so they are named here as well as in the manifest:
    # the pre-registered sensitivity check reports the primary result with and
    # without them, and a partition that needs 356 manifests opened to reconstruct
    # is one that quietly does not get run.
    degeneration_retry: bool = False
    retried_agents: str = ""

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
        present, because it would fail identically on every resume.

        A transient failure that has now happened `REPEAT_LIMIT` times on the same
        item with the same reason is also present: it was a hypothesis, the retry
        tested it, and the answer came back the same.
        """
        return set(self.resolved())

    def resolved(self) -> dict[tuple[str, str, date], LedgerEntry]:
        """Every item that will not be attempted again, latest entry winning.

        Three ways in: it completed, its reason is terminal by nature, or its reason
        has recurred on it often enough to stop being transient. The last is counted
        per (item, reason) — an item that failed once on the network and once in the
        model has one of each, which is two hypotheses rather than a confirmed one.
        """
        out: dict[tuple[str, str, date], LedgerEntry] = {}
        repeats: dict[tuple[tuple[str, str, date], str], int] = {}
        for entry in self.entries():
            if entry.status == "complete" or is_terminal(entry.reason):
                out[entry.key] = entry
                continue
            reason = entry.reason or "other"
            if reason in ALWAYS_RETRIED:
                continue
            seen = repeats[entry.key, reason] = repeats.get((entry.key, reason), 0) + 1
            if seen >= REPEAT_LIMIT:
                out[entry.key] = entry
        return out

    def exhausted(self) -> dict[tuple[str, str, date], LedgerEntry]:
        """Items resolved by repetition rather than by a terminal reason.

        Reported separately because they are a weaker claim: `missing_exhibit` says
        the filing has no exhibit, while this says only that we stopped asking.
        """
        return {
            key: entry
            for key, entry in self.resolved().items()
            if entry.status != "complete" and not is_terminal(entry.reason)
        }
