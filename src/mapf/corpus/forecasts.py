"""Loading scoreable forecasts — from the ledger, never by scanning `runs/`.

`runs/` is not a corpus. It holds `first-capture`, `first-capture-v2` and a drift of
loose UUIDs from the first live forecasts, produced under different prompts, a
different horizon and an older schema. A scoring pass that walked the directory
would find them, and several would even parse.

So the ledger is the index, exactly as it is for resume (ADR 0019). An entry there
is a promise that a specific item completed and left artifacts behind; a directory
on disk is evidence of nothing but that something once ran.

**Two refusals, both loud.**

*An item the frozen record does not contain* means the ledger and the corpus have
diverged — a hand-edited ledger, a stale file from an earlier freeze, or a run
against a corpus that no longer exists. Any of those makes the band unscoreable,
because the denominator of every rate reported afterwards would be wrong.

*A forecast that does not match its ledger entry* means the item-to-run mapping is
broken, and scoring it would attribute one ticker's forecast to another's outcome.
Checked rather than assumed for the same reason the trace is (ADR 0022): a file in
the right directory is not proof it belongs to the right item.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from pydantic import ValidationError

from mapf.core.errors import MapError
from mapf.core.models import Forecast
from mapf.corpus.ledger import Ledger, LedgerEntry
from mapf.corpus.runner import plan
from mapf.corpus.selection import Corpus

FORECAST_FILE = "forecast.json"

# A forecast is dated the day after the filing it reads (the runner sets it there),
# but the loader must not restate the runner's arithmetic or it becomes a copy that
# drifts. What it enforces is the property that matters: the forecast opens AFTER
# the filing it reads, and close enough to it to belong to the same item.
MAX_LAG_DAYS = 7


class ForecastLoadError(MapError):
    """A band's forecasts could not be assembled into a scoreable set."""


class UnknownItemError(ForecastLoadError):
    """The ledger names items the frozen corpus does not contain."""

    def __init__(self, keys: list[str]) -> None:
        self.keys = tuple(keys)
        shown = ", ".join(keys[:10]) + (f", and {len(keys) - 10} more" if len(keys) > 10 else "")
        super().__init__(
            f"{len(keys)} completed item(s) are absent from the frozen corpus: {shown}. "
            "The ledger and the frozen record have diverged, so every rate reported "
            "from this band would have the wrong denominator."
        )


class ForecastMismatchError(ForecastLoadError):
    """A stored forecast does not match the ledger entry pointing at it."""


@dataclass(frozen=True)
class Loaded:
    """One scoreable forecast, still attached to the ledger entry that found it.

    The pairing is carried rather than reconstructed. A caller that needs to
    partition the scored set — the pre-registered sensitivity checks of ADR 0020
    and ADR 0021 both do — otherwise has to re-derive which forecast belongs to
    which item from dates alone, and the forecast's `as_of` is not the filing date:
    it is the day after. Matching them by equality silently matches nothing, which
    is a partition that always reports an empty subset and looks like good news.
    """

    forecast: Forecast
    band: str
    entry: LedgerEntry

    @property
    def key(self) -> tuple[str, date]:
        """How a scored item is identified downstream: ticker and forecast date."""
        return (self.forecast.ticker, self.forecast.as_of.date())


def _read(path: Path) -> Forecast:
    try:
        return Forecast.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        # A schema mismatch lands here too, which is the point: the pre-corpus
        # captures are schema 1.x and must fail rather than be coerced.
        raise ForecastLoadError(f"{path} is not a readable v2 forecast: {error}") from error


def _check(forecast: Forecast, ticker: str, filing_date: date, run_id: str) -> None:
    if forecast.ticker != ticker:
        raise ForecastMismatchError(
            f"run {run_id} is recorded against {ticker} but its forecast is for "
            f"{forecast.ticker}; the item-to-run mapping is broken"
        )
    as_of = forecast.as_of.date()
    if not filing_date < as_of <= filing_date + timedelta(days=MAX_LAG_DAYS):
        raise ForecastMismatchError(
            f"run {run_id} ({ticker}) is recorded against the filing of {filing_date} "
            f"but forecasts as of {as_of}, which is not within {MAX_LAG_DAYS} days "
            "after it"
        )


def load_band(
    ledger: Ledger, corpus: Corpus, runs_dir: Path, band: str, split: str
) -> tuple[Loaded, ...]:
    """Every completed forecast of one band, in the frozen plan's order.

    Plan order rather than ledger order, so the scored set is a deterministic
    function of the corpus rather than of the sequence a resume happened to take.
    """
    # The split is a property of the TICKER, fixed at selection and frozen with the
    # corpus (ADR 0018): a ticker in `dev` is in `dev` in both bands, or the confound
    # the panel design removes reappears one level down.
    #
    # Filtering here rather than after scoring is deliberate. A holdout item that
    # reaches `score_band` produces a number, and a number that exists has been seen
    # — reporting selectively would leave the holdout's results in memory, which is
    # exactly what not spending it is meant to prevent (ADR 0031).
    in_split = {p.ticker for p in corpus.accepted if p.split == split}
    if not in_split:
        raise ForecastLoadError(
            f"no ticker in the frozen corpus carries split {split!r}; "
            f"splits present: {sorted({p.split for p in corpus.accepted})}"
        )
    frozen = {item.key: item for item in plan(corpus, band) if item.ticker in in_split}
    resolved = ledger.resolved()

    completed = [
        (key, entry)
        for key, entry in sorted(resolved.items())
        if entry.status == "complete" and entry.band == band
    ]
    # Membership is checked against the WHOLE plan, not this split's slice. An item of
    # the other split is not "absent from the frozen corpus" — it is simply not being
    # scored here — but an item absent from both splits still has to be refused, and
    # filtering by split before this check would have swallowed it.
    everything = {item.key for item in plan(corpus, band)}
    unknown = [f"{key[0]} {key[2]}" for key, _ in completed if key not in everything]
    if unknown:
        raise UnknownItemError(unknown)

    # A completed item that names no run cannot be located, and skipping it would
    # shrink the scored sample by exactly the items whose bookkeeping is broken.
    anonymous = [
        f"{key[0]} {key[2]}" for key, entry in completed if entry.run_id is None and key in frozen
    ]
    if anonymous:
        raise ForecastLoadError(
            f"{len(anonymous)} completed item(s) record no run id, so their forecasts "
            f"cannot be found: {', '.join(anonymous[:10])}. The ledger is damaged; "
            "these items must be re-run rather than dropped from the sample."
        )

    out: list[Loaded] = []
    for key in sorted(frozen):
        entry = resolved.get(key)
        if entry is None or entry.status != "complete" or entry.run_id is None:
            continue  # terminal failure, or not attempted: absent, not unscoreable
        forecast = _read(runs_dir / str(entry.run_id) / FORECAST_FILE)
        _check(forecast, entry.ticker, entry.filing_date, str(entry.run_id))
        out.append(Loaded(forecast=forecast, band=band, entry=entry))
    return tuple(out)


def unreferenced_runs(ledger: Ledger, runs_dir: Path) -> Iterator[str]:
    """Run directories no ledger entry points at.

    Reported, never refused, and never scored. These are the pre-corpus captures —
    `first-capture`, the loose UUIDs from the first live forecasts — and their
    existence is not an error. Naming them is how the decision to load from the
    ledger stays visible instead of being invisible good behaviour.
    """
    if not runs_dir.is_dir():
        return
    referenced = {str(e.run_id) for e in ledger.entries() if e.run_id is not None}
    for child in sorted(runs_dir.iterdir()):
        if child.is_dir() and child.name not in referenced:
            yield child.name
