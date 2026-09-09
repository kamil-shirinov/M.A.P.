"""`map runs` — the run journal, read-only.

Prints one section per document source and never a combined total. The sections are
not a presentation choice: `mapf.eval.journal` has no pooled accessor, so there is
nothing to print a combined figure from (ADR 0035).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

import typer

from mapf.bootstrap import build_price_snapshot
from mapf.cli.app import app, as_shown, fail, handle
from mapf.cli.commands.evaluate import SCORING_VINTAGE
from mapf.core.errors import MapError
from mapf.corpus.ledger import Ledger
from mapf.corpus.record import FrozenRecordError, load_frozen
from mapf.eval.journal import SOURCES, JournalEntry, LedgerItem, Source, read_journal
from mapf.settings import load

FROZEN = Path("corpus/frozen.json")
LEDGER = Path("var/corpus/ledger.jsonl")


def _ledger_items(path: Path) -> dict[str, LedgerItem] | None:
    """Which corpus item each run_id belongs to, as the ledger recorded it.

    Composed here for the same reason the exhibit map is: `mapf.corpus` sits above
    `mapf.eval`. A missing ledger is `None`, not an empty mapping — an empty one
    would answer "no run is a corpus item", where the truth is that nothing was
    looked up.

    Only resolved entries carry a run_id worth trusting; `resolved()` is the same
    view a resume and a scoring pass use, so the three cannot disagree about which
    runs the ledger claims.
    """
    if not path.is_file():
        return None
    return {
        str(entry.run_id): LedgerItem(
            ticker=entry.ticker, band=entry.band, filing_date=entry.filing_date
        )
        for entry in Ledger(path).resolved().values()
        if entry.run_id is not None
    }


def _frozen_exhibits(path: Path) -> frozenset[str] | None:
    """The `document_id` of every exhibit the frozen corpus holds.

    Composed here, at the top of the graph, and handed to the journal — which sits
    below `mapf.corpus` and must keep working in a checkout with no corpus at all.

    A missing record is `None`, not an empty set: an empty set would answer "no run
    uses a frozen exhibit", which is a claim, where the truth is that nothing was
    checked. Same distinction the field itself makes.
    """
    if not path.is_file():
        return None
    record = load_frozen(path)
    exhibits = record.get("exhibits")
    if not isinstance(exhibits, dict):
        raise FrozenRecordError(f"{path} has no exhibits section to check against")
    by_accession = exhibits.get("by_accession")
    if not isinstance(by_accession, dict):
        raise FrozenRecordError(f"{path} records no exhibits by accession")
    return frozenset(
        str(entry["document_id"])
        for entry in by_accession.values()
        if isinstance(entry, dict) and "document_id" in entry
    )


# Never "scored". The ledger says artifacts exist; whether an item was scored
# depends on its split and on `map evaluate` having run, and no per-item score is
# persisted anywhere for this to read.
RELATION_LEGEND: dict[str, str] = {
    "ledger_item": "in the pre-registered panel",
    "repeat_of_exhibit": "a frozen exhibit, but not the ledger's run for it",
    "outside_corpus": "document is not in the frozen corpus",
    "unchecked": "not compared (no frozen corpus or ledger supplied)",
}

YELLOW = typer.colors.YELLOW

# Why there is no close. Three different sentences, because they are three
# different facts and only one of them is about the calendar.
OUTCOME_LEGEND: dict[str, str] = {
    "window_open": "horizon has not elapsed yet",
    "absent_from_snapshot": "the snapshot holds no window covering this anchor",
    "not_requested": "not retrieved (no snapshot named)",
}

# What each section means, printed with it. A reader should not have to know the
# manifest schema to know whether a number in front of them is scoreable.
LEGEND: dict[str, str] = {
    "corpus": "in frozen.json — the pre-registered panel, scored by `map evaluate`",
    "edgar": "--from-edgar — outside the corpus, unscored, never pooled with it",
    "news": "news directory or RSS — outside the corpus",
    "unknown": "manifest predates document_source — not a claim either way",
}


def as_dict(entry: JournalEntry) -> dict[str, object]:
    """One journal entry as JSON. Shared with `map export` deliberately: two
    serialisers for one record are two things that drift, and the export's whole
    claim is that it says nothing the library does not already say."""
    body = asdict(entry)
    body["anchor_date"] = entry.anchor_date.isoformat()
    if entry.ledger_item is not None:
        body["ledger_item"] = {
            **asdict(entry.ledger_item),
            "filing_date": entry.ledger_item.filing_date.isoformat(),
        }
    if entry.anchor_drift is not None:
        body["anchor_drift"] = asdict(entry.anchor_drift)
    if entry.outcome is not None:
        body["outcome"] = {
            **asdict(entry.outcome),
            "trading_date": entry.outcome.trading_date.isoformat(),
            "snapshot": entry.outcome.snapshot.isoformat(),
            "retrieved_on": entry.outcome.retrieved_on.isoformat(),
        }
    return body


def _print(source: str, entries: tuple[JournalEntry, ...]) -> None:
    typer.secho(f"\n{source}  ({len(entries)})", fg=typer.colors.CYAN, bold=True)
    typer.secho(f"  {LEGEND[source]}", fg=typer.colors.BRIGHT_BLACK)
    for entry in entries:
        # Spelled out rather than a tick, and never the word "scored": a ledger
        # entry promises artifacts exist, not that anything was scored.
        relation = RELATION_LEGEND[entry.corpus_relation]
        if entry.ledger_item is not None:
            relation += f" — {entry.ledger_item.band} band, filed {entry.ledger_item.filing_date}"
        typer.echo(
            f"  {entry.anchor_date}  {entry.ticker:<6} "
            f"spot {entry.anchor_spot:>10.2f}  h={entry.horizon_days:<3} {entry.run_id[:8]}"
        )
        typer.secho(f"    corpus     {relation}", fg=typer.colors.BRIGHT_BLACK)
        if entry.arm is not None:
            # Loud, not grey: an arm is not a projection, and arm A's forecasts are
            # byte-identical to the corpus runs they replay.
            typer.secho(
                f"    arm        {entry.arm} — an ablation run, not a projection",
                fg=typer.colors.MAGENTA,
            )
        typer.echo(
            "    forecast   "
            + "  ".join(
                f"{line.name} {as_shown(line.price_return)}@{line.probability_weight:.2f}"
                for line in entry.scenarios
            )
        )
        if entry.anchor_drift is not None:
            d = entry.anchor_drift
            typer.secho(
                f"    drift      snapshot closes {d.snapshot_close:.2f} at this anchor, "
                f"forecast opened from {d.recorded_spot:.2f} (x{d.ratio:.4f}) — "
                f"scoring refuses items in this state",
                fg=typer.colors.RED,
            )
        if entry.outcome is None:
            typer.secho(f"    outcome    {OUTCOME_LEGEND[entry.outcome_status]}", fg=YELLOW)
        else:
            # Stated as a close on a date, never as a comparison to the forecast
            # above it. The comparison is a score, and this is not the place.
            # Two decimals in the listing, never in the JSON: providers hand back
            # float32 closes, so 311.29998779296875 is the honest stored value and
            # a terrible thing to read. The artifact keeps full precision.
            typer.echo(
                f"    outcome    close {entry.outcome.close:.2f} on "
                f"{entry.outcome.trading_date} ({entry.outcome.provider})"
            )
            # Where it was read from and when, said every time. The close is a
            # retrieval, and a reader must never take it for something the run
            # stored — the run's own snapshot ends at its anchor and cannot hold it.
            typer.secho(
                f"               retrieved {entry.outcome.retrieved_on} from the "
                f"{entry.outcome.snapshot} snapshot",
                fg=typer.colors.BRIGHT_BLACK,
            )


@app.command()
def runs(
    runs_dir: Path = typer.Option(Path("runs"), help="Where run artifacts live."),
    source: str | None = typer.Option(
        None, "--source", help=f"Show one population only: {', '.join(SOURCES)}."
    ),
    limit: int = typer.Option(
        20, "--limit", help="Most recent N runs by anchor date. 0 for all of them."
    ),
    snapshot: str = typer.Option(
        SCORING_VINTAGE,
        "--snapshot",
        help=(
            "The stored price vintage outcomes are read from. Pinned and READ-ONLY: "
            "a range it does not hold is reported per run, never fetched. Pass an "
            "empty string to list forecasts without retrieving any outcome."
        ),
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a listing."),
    ledger_path: Path = typer.Option(
        LEDGER,
        help=(
            "The corpus ledger, which maps a run to the item it executed. Absent, "
            "a run can only be related to the corpus by its document."
        ),
    ),
    frozen: Path = typer.Option(
        FROZEN,
        help=(
            "The frozen corpus to check each run's document against. Absent, the "
            "membership field reads as unchecked rather than as false."
        ),
    ),
    config: Path | None = typer.Option(None, help="Config file to use instead of the default."),
) -> None:
    """List what was forecast and what happened. Never a score, never pooled."""
    try:
        settings = load([config] if config else None)
        if source is not None and source not in SOURCES:
            raise fail(f"--source must be one of {', '.join(SOURCES)}, got {source!r}", 2)
        if limit < 0:
            raise fail(f"--limit must be 0 or more, got {limit}", 2)

        try:
            vintage = date.fromisoformat(snapshot) if snapshot else None
        except ValueError as err:
            raise fail(f"--snapshot must be a date, got {snapshot!r}", 2) from err

        journal = read_journal(
            runs_dir,
            # The pinned scoring vintage, not the vintage each run was produced
            # under. A run's own snapshot ends at its anchor and cannot hold the
            # outcome — the bar did not exist when it was taken (ADR 0012). Reading
            # a pinned snapshot is also what makes the value reproducible: a live
            # fetch would give a different close on a different day.
            snapshot=None if vintage is None else build_price_snapshot(settings, vintage),
            today=datetime.now(UTC).date(),
            limit=limit or None,
            frozen_exhibits=_frozen_exhibits(frozen),
            ledger_items=_ledger_items(ledger_path),
        )
        shown: tuple[Source, ...] = (source,) if source is not None else journal.populated()
        if as_json:
            typer.echo(
                json.dumps(
                    {name: [as_dict(e) for e in journal.of(name)] for name in shown},
                )
            )
            return
        gap = journal.skipped
        if gap.no_artifacts or gap.unreadable:
            typer.secho(
                f"\nskipped  {gap.no_artifacts} without artifacts, "
                f"{gap.unreadable} unreadable  (counted before --limit)",
                fg=typer.colors.YELLOW,
            )
        if not shown:
            typer.secho(f"no readable runs under {runs_dir}", fg=typer.colors.YELLOW)
            return
        for name in shown:
            _print(name, journal.of(name))
    except MapError as err:
        raise handle(err) from err
