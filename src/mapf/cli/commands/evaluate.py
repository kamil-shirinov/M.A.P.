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

**A corpus spanning frozen records.** The freeze governs sampling, truncation and
corpus membership, so a band produced under two of them is at least as serious as
one produced under two commits — and it was undetectable until manifests began
recording it, because nothing anywhere did (ADR 0022). This refusal has no override
flag: a mixed code version can be a harmless refactor, but a mixed freeze means two
items were not asked the same question.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import typer
from pydantic import ValidationError

from mapf.bootstrap import build_earnings_calendar, build_http_client, build_market_data
from mapf.cli.app import app, fail, handle
from mapf.core.errors import MapError
from mapf.core.models import PriceWindow
from mapf.corpus.forecasts import Loaded, load_band, unreferenced_runs
from mapf.corpus.ledger import Ledger
from mapf.corpus.passes import IncompletePassError, require_finished, split_passes
from mapf.corpus.runner import plan
from mapf.corpus.selection import Corpus
from mapf.data.earnings import EdgarEarningsCalendar
from mapf.eval.aggregate import Comparison, calibration_ratio, compare, leakage, summarise
from mapf.eval.scorer import BandScores, score_band
from mapf.pipeline.run import TRACE_FILE
from mapf.pipeline.trace import audit_trace
from mapf.settings import load
from mapf.settings.loader import Settings

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

        freezes = _freeze_versions(ledger, runs_dir, band)
        if len(freezes) > 1:
            typer.secho(
                f"freeze     {len(freezes)} distinct frozen records produced this band:",
                fg=typer.colors.RED,
            )
            for label, count in freezes.most_common():
                typer.echo(f"           {label}  {count} runs")
            raise fail(
                "this band was produced under more than one frozen record",
                2,
                hint=(
                    "The freeze governs sampling, truncation and corpus membership, "
                    "so these items were not asked the same question. Re-run the "
                    "items produced under the older record. There is deliberately "
                    "no override for this one."
                ),
            )
        if freezes:
            ((label, count),) = freezes.most_common()
            typer.secho(f"freeze     {label} ({count} runs)", fg=typer.colors.GREEN)

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
            ((label, count),) = versions.most_common()
            typer.secho(f"code       {label} ({count} runs)", fg=typer.colors.GREEN)

        settings = load()
        forecasts = load_band(ledger, corpus, runs_dir, band)
        typer.secho(
            f"loaded     {len(forecasts)} forecasts, from the ledger and not by "
            f"scanning {runs_dir}/",
            fg=typer.colors.GREEN,
        )
        stray = list(unreferenced_runs(ledger, runs_dir))
        if stray:
            typer.echo(
                f"           {len(stray)} run director(ies) there are referenced by no "
                "ledger entry and are not scored"
            )

        with build_http_client(settings) as client:
            calendar = build_earnings_calendar(settings, client)
            scores = _score(forecasts, settings, calendar)
            _report(scores, band, calendar)

            other = next((b.name for b in corpus.criteria.bands if b.name != band), None)
            if other is not None:
                _leakage(other, corpus, ledger, runs_dir, settings, calendar, scores)

        _sensitivity(scores, forecasts)
        raise typer.Exit(0)
    except IncompletePassError as error:
        typer.secho(f"REFUSED    {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(8) from error
    except MapError as error:
        raise handle(error) from error


def _unauditable(ledger: Ledger, runs_dir: Path, band: str) -> list[str]:
    """Completed items whose trace is missing, empty, or not one run's worth.

    56 of 57 runs once had no `trace.jsonl` and were recorded complete regardless,
    because a single shared trace wrote every item's events into the first item's
    directory. Scoring those would put a number on a forecast nobody can inspect.

    The count bound is what makes this cover the 57th. A file-exists check catches
    the 56 empty directories and passes the one holding the entire band — the
    incident's own worst artifact (ADR 0022).
    """
    out: list[str] = []
    for key, entry in sorted(ledger.resolved().items()):
        if entry.status != "complete" or entry.band != band or entry.run_id is None:
            continue
        reason = audit_trace(runs_dir / str(entry.run_id) / TRACE_FILE)
        if reason is not None:
            out.append(f"{key[0]} {key[2]} (run {entry.run_id}): {reason}")
    return out


def _freeze_versions(ledger: Ledger, runs_dir: Path, band: str) -> Counter[str]:
    """Which frozen records produced this band's completed runs.

    Band-filtered, unlike `_code_versions` below — which is audit finding #4 and is
    deferred, not overlooked.
    """
    seen: Counter[str] = Counter()
    for entry in ledger.resolved().values():
        if entry.status != "complete" or entry.band != band or entry.run_id is None:
            continue
        manifest = _manifest_of(runs_dir, entry.run_id)
        if manifest is None:
            continue
        version = manifest.get("freeze_version")
        seen[str(version) if version else "unknown (predates the field)"] += 1
    return seen


def _manifest_of(runs_dir: Path, run_id: object) -> dict[str, object] | None:
    path = runs_dir / str(run_id) / "manifest.json"
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _code_versions(ledger: Ledger, runs_dir: Path) -> Counter[str]:
    """Which commits produced the completed runs of this band.

    Reads each run's manifest rather than assuming one version per corpus. Runs
    predating the field report `unknown`, which is the honest answer for them.
    """
    seen: Counter[str] = Counter()
    for entry in ledger.resolved().values():
        if entry.status != "complete" or entry.run_id is None:
            continue
        manifest = _manifest_of(runs_dir, entry.run_id)
        if manifest is None:
            continue
        version = manifest.get("code_version")
        if not isinstance(version, dict):
            version = {}
        commit = version.get("commit")
        if commit is None:
            seen["unknown (predates the field)"] += 1
        else:
            seen[f"{commit[:12]}{'+dirty' if version.get('dirty') else ''}"] += 1
    return seen


# ---------------------------------------------------------------------------
# The adapters
# ---------------------------------------------------------------------------
def _score(
    loaded: Sequence[Loaded], settings: Settings, calendar: EdgarEarningsCalendar
) -> BandScores:
    """Fit and score everything, against one price series and one EDGAR calendar."""
    market = build_market_data(settings)

    def prices(ticker: str, start: date, end: date) -> PriceWindow:
        return market.get_ohlcv(ticker, start, end)

    return score_band(
        [(item.forecast, item.band) for item in loaded],
        prices=prices,
        # STRICTLY prior, cut inside the adapter and asserted again in `score_item`.
        # The multiplier would otherwise drop a future date silently by failing to
        # find it in an already-truncated history, which leaves a broken adapter
        # looking correct forever (ADR 0023).
        earnings=calendar.dates_before,
        history_days=settings.data.history_days,
    )


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------
def _comparisons(scores: BandScores) -> list[Comparison]:
    out: list[Comparison] = []
    for name in sorted({n for item in scores.items for n in item.baseline_crps}):
        model, base, days = scores.paired(name)
        if model:
            out.append(compare(model, base, days, name="M.A.P.", baseline=name))
    return out


def _report(scores: BandScores, band: str, calendar: EdgarEarningsCalendar) -> None:
    if not scores.items:
        raise fail(
            f"no item of the {band} band could be scored",
            2,
            hint=f"unscored by reason: {scores.unscored or 'nothing was loaded'}",
        )
    provider, adjustment = scores.items[0].provider, scores.items[0].adjustment
    typer.secho(f"vintage    {provider} / {adjustment}", fg=typer.colors.GREEN)
    typer.secho(f"scored     {scores.n} items", fg=typer.colors.GREEN)
    for reason, count in sorted(scores.unscored.items()):
        typer.echo(f"           {count} unscored: {reason}")

    typer.echo("")
    for line in summarise(_comparisons(scores)):
        typer.echo(f"  {line}")

    realised = [item.realised_return for item in scores.items]
    k = calibration_ratio([item.map_sigma for item in scores.items], realised)
    typer.echo("")
    typer.echo(
        f"  calibration: stated sigma / realised = {k:.3f} "
        f"({'over' if k > 1 else 'under'}-dispersed; 1.0 is calibrated)"
    )
    _benchmark_strength(scores, calendar)


def _benchmark_strength(scores: BandScores, calendar: EdgarEarningsCalendar) -> None:
    """How hard the earnings baseline actually was.

    A multiplier pinned at 1.0 is the random walk wearing a second name, so a band
    where most of them sit there was never compared against a benchmark that widens
    for a scheduled event. Reported as a number rather than assumed away, because
    a weak baseline flatters the result **invisibly** — the argument for `arch` over
    a hand-rolled GARCH, applied to the input (ADR 0023).
    """
    values = scores.multipliers
    if not values:
        typer.secho(
            "  earnings baseline: never fitted — it is the random walk under a "
            "second name, and any win over it should be read as such",
            fg=typer.colors.YELLOW,
        )
        return
    neutral = scores.neutral_multipliers
    median = sorted(values)[len(values) // 2]
    line = (
        f"  earnings baseline: multiplier median {median:.2f}, "
        f"neutral (1.00) on {neutral} of {len(values)}"
    )
    weak = neutral > len(values) // 2
    if weak:
        line += " — on most items this baseline declined to widen at all"
    typer.secho(line, fg=typer.colors.YELLOW if weak else typer.colors.GREEN)
    if calendar.failures:
        typer.secho(
            f"  earnings calendar: unavailable for {len(calendar.failures)} ticker(s) "
            f"({', '.join(sorted(calendar.failures)[:8])})",
            fg=typer.colors.YELLOW,
        )


def _leakage(
    other: str,
    corpus: Corpus,
    ledger: Ledger,
    runs_dir: Path,
    settings: Settings,
    calendar: EdgarEarningsCalendar,
    scores: BandScores,
) -> None:
    """The headline number, reported only when both bands are actually finished.

    A leakage estimate on a half-run band is not a preliminary version of the real
    one, which is the whole reason this command refuses an unfinished pass. So the
    other band is scored when it is complete and named as absent when it is not —
    never partially.
    """
    wanted = {item.key for item in plan(corpus, other)}
    resolved = ledger.resolved()
    outstanding = len(wanted) - sum(1 for key in wanted if key in resolved)
    if outstanding:
        typer.echo("")
        typer.secho(
            f"  leakage: not reported — the {other} band has {outstanding} of "
            f"{len(wanted)} items outstanding, and a leakage estimate on a "
            "half-finished band is a different number, not a preliminary one",
            fg=typer.colors.YELLOW,
        )
        return
    theirs = _score(load_band(ledger, corpus, runs_dir, other), settings, calendar)
    if not theirs.items:
        return
    estimate = leakage(scores.crps(), theirs.crps())
    typer.echo("")
    typer.secho(
        f"  leakage: clean {estimate.clean_mean:.5f} vs {other} "
        f"{estimate.ambiguous_mean:.5f}, difference {estimate.difference:+.5f} "
        f"[{estimate.lower:+.5f}, {estimate.upper:+.5f}], "
        f"n={estimate.clean_n}/{estimate.ambiguous_n}"
        + ("  — SUGGESTS LEAKAGE" if estimate.suggests_leakage else ""),
        fg=typer.colors.RED if estimate.suggests_leakage else typer.colors.GREEN,
    )


def _sensitivity(scores: BandScores, loaded: Sequence[Loaded]) -> None:
    """The two pre-registered robustness checks, run unconditionally.

    ADR 0020 and ADR 0021 both committed to reporting the primary result with and
    without an identified subset, *regardless of what the comparison shows*, before
    any score existed. Running them here rather than on request is what keeps that
    a pre-registration instead of an option.
    """
    # Keyed on the FORECAST date, taken from the loaded pairing. Keying on the
    # ledger's filing date would match nothing at all — a forecast opens the day
    # after the filing it reads — and an empty subset reads as "nothing was
    # affected" rather than as a broken partition.
    excluded = {
        "truncated exhibits (ADR 0020)": {i.key for i in loaded if i.entry.truncated},
        "degeneration retries (ADR 0021)": {i.key for i in loaded if i.entry.degeneration_retry},
    }
    typer.echo("")
    for label, keys in excluded.items():
        kept = tuple(i for i in scores.items if (i.ticker, i.as_of) not in keys)
        affected = scores.n - len(kept)
        if not keys:
            typer.echo(f"  sensitivity: no items in the {label} set")
            continue
        subset = BandScores(items=kept, unscored={})
        typer.echo(f"  sensitivity, excluding {label} — {affected} of {scores.n} items:")
        for line in summarise(_comparisons(subset)):
            typer.echo(f"    {line}")
