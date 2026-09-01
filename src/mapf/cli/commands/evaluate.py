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
import subprocess
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

import typer
from pydantic import ValidationError

from mapf.bootstrap import build_earnings_calendar, build_http_client, build_market_data
from mapf.cli.app import app, fail, handle
from mapf.core.errors import MapError
from mapf.core.models import PriceWindow
from mapf.core.provenance import (
    FORECAST_ROOTS,
    NOT_FORECAST_PATHS,
    code_version,
    freeze_differences,
    freeze_digest,
)
from mapf.corpus.forecasts import Loaded, load_band, unreferenced_runs
from mapf.corpus.ledger import Ledger
from mapf.corpus.passes import (
    IncompletePassError,
    require_finished,
    split_passes,
    status_of,
)
from mapf.corpus.runner import plan
from mapf.corpus.selection import Corpus
from mapf.data.earnings import EdgarEarningsCalendar
from mapf.eval.aggregate import Comparison, calibration_ratio, compare, leakage, summarise
from mapf.eval.scorer import BandScores, VintageError, require_one_vintage, score_band
from mapf.pipeline.run import TRACE_FILE
from mapf.pipeline.trace import audit_trace
from mapf.settings import load
from mapf.settings.loader import Settings

FROZEN = Path("corpus/frozen.json")
LEDGER = Path("var/corpus/ledger.jsonl")
# Committed, so the git history is the proof the holdout was spent once — the same
# argument that makes the frozen corpus commit the proof it was pre-registered.
HOLDOUT_LEDGER = Path("corpus/holdout_spend.jsonl")


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
    split: str = typer.Option(
        ...,
        "--split",
        help=(
            "Which half of the panel to score: dev or holdout. REQUIRED and without a "
            "default, so the holdout cannot be scored by omission."
        ),
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help=(
            "Structural pre-flight: exercise the whole path on real artifacts and "
            "print no scores. Reports every problem it finds rather than the first."
        ),
    ),
) -> None:
    """Score a completed band, or pre-flight the path with `--check`.

    `--check` is `map corpus run --check` one layer up. It loads from the ledger,
    applies every refusal, fetches the realised windows, fits all three baselines,
    and confirms each completed item is scoreable end to end — then prints **counts
    and reasons only**. It computes the scores, exactly as scoring does, and does not
    report them; the boundary is on what is shown, not on what is run, because a
    pre-flight that exercised a different path would not be checking this one.

    Two differences from a scoring run, both stated where they occur: the pass
    boundary is reported rather than enforced (an unfinished band is the normal case
    for a pre-flight), and leakage is skipped (it needs both bands).
    """
    problems: list[str] = []

    def refuse(line: str, *, hint: str = "") -> None:
        """Refuse now, or collect and continue under `--check`.

        A pre-flight that stopped at the first problem would have to be run once per
        problem. `map corpus run --check` reports the whole picture; so does this.
        """
        if not check:
            raise fail(line, 2, hint=hint)
        problems.append(line)

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

        splits = sorted({p.split for p in corpus.accepted})
        if split not in splits:
            raise fail(f"unknown split {split!r}", 2, hint=f"Splits: {', '.join(splits)}")

        # The holdout is spendable once, and the refusal happens BEFORE anything is
        # computed. A number that exists has been seen (ADR 0031).
        if split == "holdout" and not check:
            _refuse_if_holdout_spent(HOLDOUT_LEDGER)

        ledger = Ledger(ledger_path)
        items = plan(corpus, band)
        band_passes = split_passes(items, band=band, count=passes)
        wanted = [s.strip() for s in declared.split(",")] if declared else None

        if check:
            # SKIPPED, and named: an unfinished band is the normal case for a
            # pre-flight, so enforcing the pass boundary here would make the check
            # unusable for exactly the situation it exists to serve.
            statuses = tuple(status_of(p, ledger) for p in band_passes)
        else:
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
            refuse(
                f"{len(unauditable)} items cannot be audited",
                hint=(
                    "Full provenance is the claim the result rests on. Re-run the "
                    "affected items; a forecast whose trace is missing or empty is "
                    "not one this project can defend."
                ),
            )
        else:
            typer.secho("trace      every completed item has a trace", fg=typer.colors.GREEN)

        freezes, freeze_example = _freeze_versions(ledger, runs_dir, band)
        if len(freezes) > 1:
            typer.secho(
                f"freeze     {len(freezes)} distinct forecast-governing records "
                "produced this band:",
                fg=typer.colors.RED,
            )
            for label, count in freezes.most_common():
                typer.echo(f"           {label}  {count} runs")
            for field in _freeze_diff(freeze_example):
                typer.echo(f"           differs: {field}")
            refuse(
                "this band was produced under more than one frozen record",
                hint=(
                    "The fields listed above are what differ, and each governs what "
                    "a model was asked. Re-run the items produced under the older "
                    "record. There is deliberately no override for this one — a "
                    "version bump that changes no governing field no longer reaches "
                    "here (ADR 0029)."
                ),
            )
        elif freezes:
            # `elif`, because under `--check` the refusal above collects and returns
            # rather than raising — so this line is reachable with two versions in
            # hand, and would unpack a two-element list into one name.
            ((label, count),) = freezes.most_common()
            typer.secho(f"freeze     {label} ({count} runs)", fg=typer.colors.GREEN)

        versions, example = _code_versions(ledger, runs_dir)
        if not versions:
            typer.secho("code       no manifests found to read", fg=typer.colors.YELLOW)
        elif len(versions) > 1:
            typer.secho(
                f"code       {len(versions)} distinct forecast digests produced this band:",
                fg=typer.colors.YELLOW,
            )
            for label, count in versions.most_common():
                typer.echo(f"           {label}  {count} runs")
            for path in _forecast_diff(example):
                typer.echo(f"           differs: {path}")
            if not allow_mixed_code:
                refuse(
                    "this band was produced by more than one forecast digest",
                    hint=(
                        "The files listed above are what differ. If they cannot "
                        "change a forecast, --allow-mixed-code records that "
                        "judgement; if they can, re-run the affected items."
                    ),
                )
        else:
            ((label, count),) = versions.most_common()
            typer.secho(f"code       digest {label} ({count} runs)", fg=typer.colors.GREEN)

        settings = load()
        forecasts = load_band(ledger, corpus, runs_dir, band, split)
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
            # Computed identically in both modes. `--check` withholds the scores; it
            # does not avoid producing them, because a path that skipped the
            # computation would not be exercising the one that matters.
            scores = _score(forecasts, settings, calendar, strict=not check)
            # BEFORE anything is printed. See `_record_holdout_spend`.
            if split == "holdout" and not check:
                _record_holdout_spend(HOLDOUT_LEDGER, band=band, items=scores.n, record=record)
            if check:
                _structural(scores, forecasts, calendar, refuse)
            else:
                _report(scores, band, calendar)
                other = next((b.name for b in corpus.criteria.bands if b.name != band), None)
                if other is not None:
                    _leakage(other, corpus, ledger, runs_dir, settings, calendar, scores, split)

        _sensitivity(scores, forecasts, counts_only=check)

        if not check:
            raise typer.Exit(0)
        typer.echo("")
        if problems:
            typer.secho(
                f"check      {len(problems)} problem(s) would refuse a scoring run:",
                fg=typer.colors.RED,
            )
            for line in problems:
                typer.echo(f"           {line}")
            raise typer.Exit(2)
        typer.secho(
            "check      the whole path runs on real artifacts; no scores printed",
            fg=typer.colors.GREEN,
        )
        raise typer.Exit(0)
    except IncompletePassError as error:
        typer.secho(f"REFUSED    {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(8) from error
    except MapError as error:
        raise handle(error) from error


def _refuse_if_holdout_spent(path: Path) -> None:
    """The holdout is spendable exactly once, and the record is what enforces it.

    A holdout protects against a result chosen after seeing it. That protection is
    gone the moment the numbers are looked at a second time with a changed model
    in between, and *intending* to look once is not a mechanism — this project has
    now watched a rule enforced by intention fail twice (ADR 0019 §8).

    The record is committed, so the git history is the proof it was spent once, in
    exactly the way the frozen corpus commit is the proof the corpus was
    pre-registered. An absence here is checkable; a promise is not.
    """
    if not path.is_file():
        return
    spent = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not spent:
        return
    first = json.loads(spent[0])
    raise fail(
        f"the holdout was already scored on {first.get('scored_on')}",
        9,
        hint=(
            f"Recorded in {path}: code {str(first.get('forecast_digest'))[:12]}, freeze "
            f"{first.get('freeze_version')}, calibration "
            f"{first.get('calibration') or 'none fitted'}. A holdout scored twice is not "
            "a holdout. If a genuinely new question needs it, that is a decision to "
            "write down and defend, not a flag to pass."
        ),
    )


def _record_holdout_spend(path: Path, *, band: str, items: int, record: dict[str, object]) -> None:
    """Append the spend BEFORE any number is shown.

    The ordering is the point: the spend happens when the numbers are seen, so a
    crash between computing and displaying must leave the holdout spent rather than
    apparently intact. Erring the other way would let a repeated run be justified as
    "the last one did not finish".
    """
    version = code_version()
    entry = {
        "scored_on": date.today().isoformat(),
        "band": band,
        "items": items,
        "commit": version.commit,
        "forecast_digest": version.forecast_digest,
        "freeze_version": record.get("freeze_version"),
        "freeze_digest": freeze_digest(record, truncated=False),
        # Phase 3 has fitted nothing yet, and the first spend should say so rather
        # than leave the field absent and ambiguous.
        "calibration": None,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


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


def _freeze_versions(
    ledger: Ledger, runs_dir: Path, band: str
) -> tuple[Counter[str], dict[str, str]]:
    """Which frozen records produced this band's completed runs, keyed by **digest**.

    The version is the wrong equality test, for the same reason the commit was
    (ADR 0026, ADR 0029): it moves for reasons that cannot change a forecast. Noting
    the execution order took the freeze from 2.3.0 to 2.4.0 while every field
    deciding what a model is asked stayed identical — and comparing versions would
    have refused the band on a restart, with no override.

    Band-filtered, unlike `_code_versions` below — which is audit finding #4 and is
    deferred, not overlooked.

    Returns the counts and one representative commit per group, so two differing
    records can be recovered from git and the differing fields named.
    """
    seen: Counter[str] = Counter()
    example: dict[str, str] = {}
    versions: dict[str, set[str]] = {}
    for entry in ledger.resolved().values():
        if entry.status != "complete" or entry.band != band or entry.run_id is None:
            continue
        manifest = _manifest_of(runs_dir, entry.run_id)
        if manifest is None:
            continue
        digest, version = manifest.get("freeze_digest"), manifest.get("freeze_version")
        code = manifest.get("code_version")
        if digest:
            # The KEY is the digest alone. Putting the version in it would split a
            # group whose governing content is identical — which is the failure this
            # whole change exists to remove, reintroduced in a display string.
            label = str(digest)[:12]
            versions.setdefault(label, set()).add(str(version or "?"))
            if isinstance(code, dict) and code.get("commit"):
                example.setdefault(label, str(code["commit"]))
        elif version:
            label = f"v{version} (predates the digest)"
        else:
            label = "unknown (predates the field)"
        seen[label] += 1
    # Versions are rendered beside the digest, never folded into it: a reader wants
    # to know which record labels share governing content.
    return (
        Counter(
            {
                (f"{k} (v{', v'.join(sorted(versions[k]))})" if k in versions else k): n
                for k, n in seen.items()
            }
        ),
        {
            f"{k} (v{', v'.join(sorted(versions[k]))})" if k in versions else k: v
            for k, v in example.items()
        },
    )


def _freeze_diff(example: dict[str, str]) -> list[str]:
    """Which forecast-governing fields differ between two frozen records.

    Recovered from git by the commit each group ran under, the same way the code
    digest's file list is: a refusal should hand over what to look at.
    """
    commits = [c for c in example.values() if c]
    if len(commits) != 2:
        return []
    records = [_frozen_at(c) for c in commits]
    if any(r is None for r in records):
        return []
    return freeze_differences(records[0] or {}, records[1] or {})


def _frozen_at(commit: str) -> dict[str, object] | None:
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "show", f"{commit}:corpus/frozen.json"],
            capture_output=True,
            text=True,
            timeout=10.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        loaded = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _manifest_of(runs_dir: Path, run_id: object) -> dict[str, object] | None:
    path = runs_dir / str(run_id) / "manifest.json"
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _code_versions(ledger: Ledger, runs_dir: Path) -> tuple[Counter[str], dict[str, str]]:
    """What produced this band's completed runs, keyed by **forecast digest**.

    The commit is the wrong equality test. Development continues while a corpus
    runs, so a twelve-night band spans every commit made during it — and a guard
    that must be overridden on every run is not a guard (ADR 0026). Two runs sharing
    a digest are forecast-equivalent however many commits separate them.

    Returns the counts and one representative commit per digest, so a differing pair
    can be diffed and the override made on evidence rather than blind.

    A dirty-tree run has no honest digest and is counted apart rather than grouped
    with anything: its commit does not describe the files that ran.
    """
    seen: Counter[str] = Counter()
    example: dict[str, str] = {}
    for entry in ledger.resolved().values():
        if entry.status != "complete" or entry.run_id is None:
            continue
        manifest = _manifest_of(runs_dir, entry.run_id)
        if manifest is None:
            continue
        version = manifest.get("code_version")
        if not isinstance(version, dict):
            version = {}
        digest, commit = version.get("forecast_digest"), version.get("commit")
        if version.get("dirty"):
            label = f"{str(commit)[:12]}+dirty (no digest)"
        elif digest:
            label = str(digest)[:12]
            example.setdefault(label, str(commit))
        elif commit:
            label = f"{str(commit)[:12]} (predates the digest)"
        else:
            label = "unknown (predates the field)"
        seen[label] += 1
    return seen, example


def _forecast_diff(example: dict[str, str]) -> list[str]:
    """The forecast-producing files that differ between two digests.

    Turns the refusal into evidence. The band's first split was three files of
    scoring-only additions — a config key, a settings field and a bootstrap function
    used only by `map evaluate` — which is an override anyone can justify in one
    glance, and indistinguishable from a real change without this.
    """
    commits = [c for c in example.values() if c]
    if len(commits) != 2:
        return []
    out = _git_names(commits[0], commits[1])
    return [p for p in out if not p.startswith(NOT_FORECAST_PATHS)]


def _git_names(left: str, right: str) -> list[str]:
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "diff", "--name-only", left, right, "--", *FORECAST_ROOTS],
            capture_output=True,
            text=True,
            timeout=10.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in result.stdout.splitlines() if line] if result.returncode == 0 else []


# ---------------------------------------------------------------------------
# The adapters
# ---------------------------------------------------------------------------
def _score(
    loaded: Sequence[Loaded],
    settings: Settings,
    calendar: EdgarEarningsCalendar,
    *,
    strict: bool = True,
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
        strict=strict,
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


def _structural(
    scores: BandScores,
    loaded: Sequence[Loaded],
    calendar: EdgarEarningsCalendar,
    refuse: Callable[..., None],
) -> None:
    """Counts and reasons. Never a score.

    The same boundary the corpus runner holds between health and result (ADR 0019
    §7), one layer up: everything here says whether the machine works, and nothing
    says whether the forecasts are any good.
    """
    typer.echo("")
    typer.secho(f"scoreable  {scores.n} of {len(loaded)} loaded items", fg=typer.colors.GREEN)
    if scores.unscored:
        for reason, count in sorted(scores.unscored.items()):
            typer.secho(f"           {count} unscored: {reason}", fg=typer.colors.YELLOW)
        refuse(f"{sum(scores.unscored.values())} completed item(s) could not be scored")

    vintages = sorted({(i.provider, i.adjustment) for i in scores.items})
    for provider, adjustment in vintages:
        n = sum(1 for i in scores.items if (i.provider, i.adjustment) == (provider, adjustment))
        typer.echo(f"vintage    {provider} / {adjustment}  ({n} items)")
    try:
        # The same refusal a scoring run makes, run here so it can be REPORTED
        # beside the other problems instead of ending the pre-flight on the first.
        require_one_vintage(scores.items)
    except VintageError as error:
        refuse(str(error).split(".")[0])

    names = sorted({n for item in scores.items for n in item.baseline_crps})
    for name in names:
        fitted = sum(1 for i in scores.items if name in i.baseline_crps)
        typer.echo(f"baseline   {name:<28}{fitted:>4} of {scores.n} fitted")
    for expected in ("random_walk", "garch", "earnings_scaled_random_walk"):
        if expected not in names:
            typer.secho(f"baseline   {expected:<28}   0 fitted", fg=typer.colors.YELLOW)
            refuse(f"the {expected} baseline was never fitted on this band")

    if scores.multipliers:
        neutral = scores.neutral_multipliers
        typer.echo(
            f"multiplier {len(scores.multipliers)} fitted, {neutral} neutral (1.00) — "
            "a neutral one is the random walk under a second name"
        )
    if calendar.failures:
        typer.secho(
            f"calendar   unavailable for {len(calendar.failures)} ticker(s): "
            f"{', '.join(sorted(calendar.failures)[:8])}",
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
    split: str,
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
    theirs = _score(load_band(ledger, corpus, runs_dir, other, split), settings, calendar)
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


def _sensitivity(
    scores: BandScores, loaded: Sequence[Loaded], *, counts_only: bool = False
) -> None:
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
        typer.echo(f"  sensitivity, excluding {label} — {affected} of {scores.n} items:")
        if counts_only:
            # Membership is structural and is named; the comparison is a score and
            # is not. A partition reported only as a count cannot be checked against
            # the ledger, and an empty one reads as reassurance (finding #27).
            for ticker, day in sorted(keys & {i.key for i in loaded}):
                typer.echo(f"    {ticker} {day}")
            continue
        subset = BandScores(items=kept, unscored={})
        for line in summarise(_comparisons(subset)):
            typer.echo(f"    {line}")
