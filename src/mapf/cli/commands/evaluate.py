"""`map evaluate` — the scores, and the only place they appear.

Kept separate from `map corpus run` on purpose (ADR 0019 §2). The runner reports
health and prints no score, so nothing it shows during twelve nights can inform the
decision to continue. That separation is worth nothing if this command will answer
on a half-finished band, so it refuses.

Two refusals, and they are the substance of the command rather than error handling:

**An unfinished declared pass.** A leakage estimate on half a band is not a
preliminary version of the real number, it is a different number, and looking at it
before deciding whether to run the second half is exactly the data-dependent
stopping the two-pass design exists to prevent.

**A corpus spanning code versions, unless acknowledged.** Manifests record the
commit each run executed under. Scoring across two of them is sometimes fine and
sometimes the explanation for everything, so it is surfaced rather than averaged.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import typer
from pydantic import ValidationError

from mapf.cli.app import app, fail, handle
from mapf.core.errors import MapError
from mapf.corpus.ledger import Ledger
from mapf.corpus.passes import IncompletePassError, require_finished, split_passes
from mapf.corpus.runner import plan
from mapf.corpus.selection import Corpus

FROZEN = Path("corpus/frozen.json")
LEDGER = Path("var/corpus/ledger.jsonl")


@app.command()
def evaluate(
    band: str = typer.Option("clean", help="Which band to score."),
    frozen: Path = typer.Option(FROZEN, help="The frozen corpus."),
    ledger_path: Path = typer.Option(LEDGER, help="Where item outcomes were recorded."),
    runs_dir: Path = typer.Option(Path("runs"), help="Where run artifacts live."),
    passes: int = typer.Option(2, help="Passes the band was split into."),
    declared: str | None = typer.Option(
        None,
        help=(
            "Comma-separated pass labels that were actually meant to run. Stopping "
            "after the first half is legitimate — but it has to be declared."
        ),
    ),
    allow_mixed_code: bool = typer.Option(
        False,
        "--allow-mixed-code",
        help="Score even though runs executed under different commits.",
    ),
) -> None:
    """Score a completed band. Refuses on an unfinished pass."""
    try:
        if not frozen.is_file():
            raise fail(f"no frozen corpus at {frozen}", 5)
        try:
            record = json.loads(frozen.read_text(encoding="utf-8"))
            corpus = Corpus.model_validate(record["corpus"])
        except (json.JSONDecodeError, KeyError, ValidationError) as error:
            raise fail(
                f"{frozen} is not a readable frozen corpus: {error}",
                5,
                hint="Re-freeze it, or point --frozen at the committed artifact.",
            ) from error
        if passes < 1:
            raise fail(f"--passes must be at least 1, got {passes}", 2)
        if band not in {b.name for b in corpus.criteria.bands}:
            raise fail(
                f"unknown band {band!r}",
                2,
                hint=f"Bands: {', '.join(b.name for b in corpus.criteria.bands)}",
            )

        ledger = Ledger(ledger_path)
        items = plan(corpus, band)
        band_passes = split_passes(items, band=band, count=passes)
        wanted = [s.strip() for s in declared.split(",")] if declared else None

        statuses = require_finished(band_passes, ledger, declared=wanted)
        for status in statuses:
            mark = "complete" if status.finished else "not run"
            typer.echo(
                f"pass       {status.label:<22}{status.complete:>4} complete, "
                f"{status.terminal:>2} terminal, {status.remaining:>4} outstanding  [{mark}]"
            )

        unauditable = _unauditable(ledger, runs_dir, band)
        if unauditable:
            typer.secho(
                f"trace      {len(unauditable)} completed items have no usable trace",
                fg=typer.colors.RED,
            )
            for label in unauditable[:10]:
                typer.echo(f"           {label}")
            raise fail(
                f"{len(unauditable)} items cannot be audited",
                2,
                hint=(
                    "Full provenance is the claim the result rests on. Re-run the "
                    "affected items; a forecast whose trace is missing or empty is "
                    "not one this project can defend."
                ),
            )
        typer.secho("trace      every completed item has a trace", fg=typer.colors.GREEN)

        versions = _code_versions(ledger, runs_dir)
        if not versions:
            typer.secho("code       no manifests found to read", fg=typer.colors.YELLOW)
        elif len(versions) > 1:
            typer.secho(
                f"code       {len(versions)} distinct commits produced this band:",
                fg=typer.colors.YELLOW,
            )
            for label, count in versions.most_common():
                typer.echo(f"           {label}  {count} runs")
            if not allow_mixed_code:
                raise fail(
                    "this band was produced by more than one code version",
                    2,
                    hint=(
                        "Sometimes fine, sometimes the explanation for everything. "
                        "Re-run the affected items, or pass --allow-mixed-code to "
                        "score anyway with the split recorded above."
                    ),
                )
        else:
            (label, count), = versions.most_common()
            typer.secho(f"code       {label} ({count} runs)", fg=typer.colors.GREEN)

        typer.secho(
            "scoring    not yet implemented: baselines, Monte Carlo and the "
            "aggregation exist, the per-item scoring pass does not",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(0)
    except IncompletePassError as error:
        typer.secho(f"REFUSED    {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(8) from error
    except MapError as error:
        raise handle(error) from error


def _unauditable(ledger: Ledger, runs_dir: Path, band: str) -> list[str]:
    """Completed items whose trace is missing or empty.

    56 of 57 runs once had no `trace.jsonl` and were recorded complete regardless,
    because a single shared trace wrote every item's events into the first item's
    directory. Scoring those would put a number on a forecast nobody can inspect.
    """
    out: list[str] = []
    for key, entry in sorted(ledger.resolved().items()):
        if entry.status != "complete" or entry.band != band or entry.run_id is None:
            continue
        path = runs_dir / str(entry.run_id) / "trace.jsonl"
        if not path.is_file() or path.stat().st_size == 0:
            out.append(f"{key[0]} {key[2]} (run {entry.run_id})")
    return out


def _code_versions(ledger: Ledger, runs_dir: Path) -> Counter[str]:
    """Which commits produced the completed runs of this band.

    Reads each run's manifest rather than assuming one version per corpus. Runs
    predating the field report `unknown`, which is the honest answer for them.
    """
    seen: Counter[str] = Counter()
    for entry in ledger.resolved().values():
        if entry.status != "complete" or entry.run_id is None:
            continue
        path = runs_dir / str(entry.run_id) / "manifest.json"
        if not path.is_file():
            continue
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        version = manifest.get("code_version") or {}
        commit = version.get("commit")
        if commit is None:
            seen["unknown (predates the field)"] += 1
        else:
            seen[f"{commit[:12]}{'+dirty' if version.get('dirty') else ''}"] += 1
    return seen
