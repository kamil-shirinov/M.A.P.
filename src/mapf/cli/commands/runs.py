"""`map runs` — the run journal, read-only.

Prints one section per document source and never a combined total. The sections are
not a presentation choice: `mapf.eval.journal` has no pooled accessor, so there is
nothing to print a combined figure from (ADR 0035).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import typer

from mapf.bootstrap import build_market_data
from mapf.cli.app import app, as_shown, fail, handle
from mapf.core.errors import MapError
from mapf.corpus.record import FrozenRecordError, load_frozen
from mapf.eval.journal import SOURCES, JournalEntry, Source, read_journal
from mapf.settings import load

FROZEN = Path("corpus/frozen.json")


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


# What each section means, printed with it. A reader should not have to know the
# manifest schema to know whether a number in front of them is scoreable.
LEGEND: dict[str, str] = {
    "corpus": "in frozen.json — the pre-registered panel, scored by `map evaluate`",
    "edgar": "--from-edgar — outside the corpus, unscored, never pooled with it",
    "news": "news directory or RSS — outside the corpus",
    "unknown": "manifest predates document_source — not a claim either way",
}


def _as_dict(entry: JournalEntry) -> dict[str, object]:
    body = asdict(entry)
    body["anchor_date"] = entry.anchor_date.isoformat()
    body["window_elapsed"] = entry.window_elapsed
    if entry.outcome is not None:
        body["outcome"] = {
            **asdict(entry.outcome),
            "trading_date": entry.outcome.trading_date.isoformat(),
        }
    return body


def _print(source: str, entries: tuple[JournalEntry, ...]) -> None:
    typer.secho(f"\n{source}  ({len(entries)})", fg=typer.colors.CYAN, bold=True)
    typer.secho(f"  {LEGEND[source]}", fg=typer.colors.BRIGHT_BLACK)
    for entry in entries:
        # Spelled out rather than a tick: the reader has to see that "unchecked"
        # is a third state, and a blank column would read as "no".
        membership = {
            True: "document is a frozen exhibit",
            False: "document is not in the frozen corpus",
            None: "not checked against a frozen corpus",
        }[entry.document_is_frozen_exhibit]
        typer.echo(
            f"  {entry.anchor_date}  {entry.ticker:<6} "
            f"spot {entry.anchor_spot:>10.2f}  h={entry.horizon_days:<3} {entry.run_id[:8]}"
        )
        typer.secho(f"    exhibit    {membership}", fg=typer.colors.BRIGHT_BLACK)
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
        if entry.outcome is None:
            typer.secho("    outcome    window still open", fg=typer.colors.YELLOW)
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


@app.command()
def runs(
    runs_dir: Path = typer.Option(Path("runs"), help="Where run artifacts live."),
    source: str | None = typer.Option(
        None, "--source", help=f"Show one population only: {', '.join(SOURCES)}."
    ),
    limit: int = typer.Option(
        20, "--limit", help="Most recent N runs by anchor date. 0 for all of them."
    ),
    offline: bool = typer.Option(
        False, "--offline", help="Skip the outcome fetch; every window reads as open."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a listing."),
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

        journal = read_journal(
            runs_dir,
            # Live prices, so a window that closed since the run is visible. This is
            # why it is not a score: the scoring vintage is pinned and read-only
            # (ADR 0012), and a number from this series would not be reproducible.
            market=None if offline else build_market_data(settings),
            today=datetime.now(UTC).date(),
            limit=limit or None,
            frozen_exhibits=_frozen_exhibits(frozen),
        )
        shown: tuple[Source, ...] = (source,) if source is not None else journal.populated()
        if as_json:
            typer.echo(
                json.dumps(
                    {name: [_as_dict(e) for e in journal.of(name)] for name in shown},
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
