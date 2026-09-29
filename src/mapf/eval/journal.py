"""The run journal — what was forecast, and what happened. Never a score.

This reads `runs/` and pairs each forecast with the close its horizon landed on. It
looks like the front half of an evaluation and it is deliberately not one, so the
two constraints that keep it honest are built into the types rather than written in
a comment someone can read past.

**Nothing here is a score, and nothing here can become one by accident.**
A journal entry carries the three scenarios and, where the window has elapsed, the
realised close. It carries no error, no return, no hit, no rank — and offers no
method that takes both sides. The difference matters because scoring this set would
be scoring a sample nobody selected: `runs/` is whatever has been run, which is a
population defined after the fact by curiosity, retries and interrupted evenings.
An accuracy number over it would be a real number computed over an unreal sample,
and it would be quoted. The pre-registered panel is `corpus/frozen.json`, scored by
`map evaluate` against a pinned vintage, with the holdout spendable once (ADR 0031).
An import-linter contract holds the line: this module may not import the scoring
machinery.

**Corpus and live runs cannot be pooled, because there is no pooled accessor.**
`Journal` exposes `corpus`, `edgar`, `news` and `unknown` separately and has no
`__iter__`, no `__len__`, and no combined tuple. A caller that wants everything must
name each population, which is the point: an `--from-edgar` run is outside
`frozen.json` by construction, and a listing that concatenated them would put an
out-of-corpus item one `sum()` away from a corpus statistic. The four names are the
manifest's own `document_source` values (ADR 0034), not a grouping invented here.

`unknown` is runs whose manifest predates that field. It is a real third state, not
a synonym for either, and it is reported as itself.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import structlog
from pydantic import BaseModel, ConfigDict, ValidationError

from mapf.core.models import Forecast, PriceWindow
from mapf.core.ports import PriceSnapshotIndex
from mapf.eval.window import (
    SPOT_TOLERANCE,
    ScoringError,
    WindowNotClosedError,
    realised_bar,
)

_logger = structlog.get_logger(__name__)

Source = Literal["corpus", "edgar", "news", "unknown"]
SOURCES: tuple[Source, ...] = ("corpus", "edgar", "news", "unknown")

# How a run stands to the pre-registered panel. ONE enum rather than two booleans:
# `document_is_frozen_exhibit` and `is_a_ledger_item` would give four combinations,
# and one of them — not a frozen exhibit but a ledger item — cannot happen. It means
# the ledger and the corpus have diverged, which is a loud failure elsewhere
# (`UnknownItemError`), not a state a consumer should be invited to render.
#
#   "ledger_item"        the ledger maps this run_id to a frozen corpus item. The
#                        strongest claim here, and NOT a claim that it was scored:
#                        a ledger entry promises artifacts exist. Whether an item
#                        was scored depends on its split and on `map evaluate`
#                        having run, and no per-item score is persisted anywhere.
#   "repeat_of_exhibit"  the document is a frozen exhibit, but no ledger entry
#                        points at this run — a re-run, a post-band repeat, an
#                        ablation replay. 74 of the 775 matching runs are this.
#   "outside_corpus"     the document is not one the corpus froze.
#   "unchecked"          neither map was supplied, so nothing was compared.
CorpusRelation = Literal["ledger_item", "repeat_of_exhibit", "outside_corpus", "unchecked"]


@dataclass(frozen=True)
class LedgerItem:
    """Which corpus item a run_id belongs to, as the ledger recorded it.

    Band and filing date are CARRIED, never re-derived. A corpus forecast is dated
    the day AFTER the filing it reads, so reconstructing the filing date from the
    anchor is off by a day and matching on it silently matches nothing — the same
    trap `Loaded` documents on the scoring side. The consumer is given the values
    the ledger actually holds.
    """

    ticker: str
    band: str
    filing_date: date


class _StoredPrices(BaseModel):
    """Only the field the journal needs out of `prices`."""

    model_config = ConfigDict(extra="ignore")

    last_trading_date: date


class StoredManifest(BaseModel):
    """A READER's view of `manifest.json`, deliberately not `RunManifest`.

    `RunManifest` is the writer's schema. Its `manifest_version` is a `Literal`
    pinned to the current format, which is exactly right when stamping a new run and
    unusable for reading old ones: the moment a field is added and the version moves
    to 1.8.0, every 1.7.0 manifest on disk stops validating. All 831 of them did.

    That was invisible until now because the only other reader — `map evaluate` —
    parses manifests as raw dicts and picks fields out by hand. This is the same
    decision made once, with types: extra fields are ignored so any version parses,
    the version itself is carried as a plain string so a listing can report which
    format a run was written in, and the four fields the journal actually depends
    on are validated. It asserts what it needs and nothing more, which is the only
    contract a reader of eight format versions can honestly offer.
    """

    model_config = ConfigDict(extra="ignore")

    manifest_version: str = ""
    prices: _StoredPrices
    document_source: Literal["corpus", "edgar", "news"] | None = None
    company_name: str | None = None
    freeze_version: str | None = None
    arm: str | None = None


@dataclass(frozen=True)
class ScenarioLine:
    """One branch, exactly as the artifact stores it. No derived field."""

    name: str
    probability_weight: float
    price_return: float
    annualised_vol: float


# What is known about a run's horizon, stated per run rather than implied by a
# missing value. `None` for the outcome answers "there is no close here" without
# saying why, and the three reasons have nothing in common: the window is still
# open, the snapshot does not reach it, or nobody asked.
OutcomeStatus = Literal["closed", "window_open", "absent_from_snapshot", "not_requested"]


@dataclass(frozen=True)
class AnchorDrift:
    """The snapshot disagrees with the price the forecast was produced from.

    A corporate action applied after the run — the corpus holds one, a 1.012 split
    — re-bases every prior close, so the anchor bar in a later snapshot is not the
    bar the forecast opened on. Scoring refuses an item in this state
    (`SpotDriftError`), because a return whose endpoints come from two adjustment
    bases is wrong while every individual number stays plausible.

    **Named for what it checks, not for what scoring does about it.** "Scoring
    declined this" would be false for the three drifted runs no scoring pass ever
    attempted — one repeat, two outside the corpus. The drift is a fact about the
    price series; the consequence for scoring is a consequence.

    Reported rather than hidden, and reported rather than used to drop the outcome:
    an outcome that exists and is not comparable is a different fact from an
    outcome that does not exist, and the journal never omits a row (ADR 0035).
    """

    recorded_spot: float
    snapshot_close: float
    ratio: float


@dataclass(frozen=True)
class Outcome:
    """A close RETRIEVED from a named snapshot. Never a stored result.

    Every field here exists so the number can be attributed rather than asserted:

    `snapshot` is the vintage it was read from — the pinned, read-only series
    scoring uses, not the vintage the run itself was produced under. The run's own
    snapshot ends at its anchor and structurally cannot hold the outcome: the bar
    did not exist when that snapshot was taken. `RealisedDriftError`'s docstring
    states the same asymmetry from the scoring side.

    `retrieved_on` is when this read happened. With `snapshot` it makes the value
    reproducible — the same vintage yields the same close on any later day — and
    makes it visibly a retrieval rather than something the artifact stored.

    `provider` and `adjustment` come from the parquet file's own metadata, not from
    a caller's assumption. A close without them is not comparable to anything
    (ADR 0003), and one attributed to the wrong source fails silently.
    """

    trading_date: date
    close: float
    provider: str
    adjustment: str
    snapshot: date
    retrieved_on: date


@dataclass(frozen=True)
class JournalEntry:
    """One run: the anchor, what was forecast from it, and what followed.

    `outcome is None` means the horizon has not elapsed yet — the series does not
    hold enough sessions after the anchor. Reported as an open window rather than
    omitted, because a listing that silently dropped unfinished runs would shrink
    with the calendar and look like a shorter history than it is.
    """

    run_id: str
    ticker: str
    # Recorded at run time, because nothing downstream can resolve a name for a
    # company outside the frozen 120: the journal looks names up in universe.json,
    # which holds only those. None on runs made before the field existed, which is
    # a real state and not a blank.
    company_name: str | None
    anchor_date: date
    anchor_spot: float
    horizon_days: int
    scenarios: tuple[ScenarioLine, ...]
    document_source: Source
    freeze_version: str | None
    # Which experimental arm produced this, or None. Surfaced because recording it
    # and not showing it would leave the harm it exists to prevent: arm A is a
    # byte-identical replay, and a reader has to be able to see that.
    arm: str | None
    # DERIVED, and named for exactly what it checks. `document_source` above is
    # what the writer recorded; this is a positive equality test between two frozen
    # records -- the forecast's `source_doc_ids` against the `document_id` of every
    # exhibit in `frozen.json` -- run at read time by a caller that supplies the
    # map. It is never written into an artifact and never overwrites what was.
    #
    # It does NOT mean "this run is the corpus item", and must not be renamed to
    # anything that suggests it does. 775 of the 780 readable runs match a frozen
    # exhibit while the ledger references 701: the surplus is re-runs and repeats
    # of the same document. A `--from-edgar` run would match too, if the filer's
    # latest Item 2.02 happens to be one the corpus froze -- the document really is
    # a corpus exhibit; the run is not a corpus run. Only the ledger answers that.
    #
    # `None` means no map was supplied, so nothing was checked. Distinct from
    # `False`, which is a claim.
    document_is_frozen_exhibit: bool | None
    # Where this run stands to the pre-registered panel, in one value. Derived at
    # read time from two frozen records plus the ledger, all passed in.
    corpus_relation: CorpusRelation
    # The corpus item the ledger maps this run to, or None. Present only when
    # `corpus_relation` is "ledger_item"; it carries band and filing date so a
    # consumer never re-derives them from the anchor.
    ledger_item: LedgerItem | None
    # Set when the snapshot's close at the anchor disagrees with `anchor_spot`
    # beyond `SPOT_TOLERANCE`. `None` means they agree OR that no window was
    # available to compare — `outcome_status` says which: the check is possible
    # exactly when it reads "closed" or "window_open".
    anchor_drift: AnchorDrift | None
    outcome: Outcome | None
    # Why there is or is not a close, per run. It replaces a `window_elapsed`
    # boolean, which could not tell "the horizon has not elapsed" from "the
    # snapshot does not reach this ticker" — and answering the second as though it
    # were the first is a claim about the calendar made from a missing file.
    outcome_status: OutcomeStatus


@dataclass(frozen=True)
class Skipped:
    """Directories the listing could not place, counted rather than dropped.

    47 of the 826 run directories are not readable runs — 46 pre-manifest captures
    from the first live forecasts, and one schema 1.0.0 forecast whose
    `price_modifier_pct` is percentage points rather than a fraction (ADR 0012) —
    and a listing that omitted them silently would look like a complete history of
    a smaller number of runs. The same reason open windows are reported as open
    rather than filtered out.

    Counted over the whole directory, before `limit`: it answers "what is here that
    this cannot show", which a limit must not change.
    """

    no_artifacts: int = 0
    unreadable: int = 0


class Journal:
    """Runs grouped by where their document came from, with no way to pool them.

    The absence of `__iter__` and `__len__` is the feature. Every read names one
    population, so a corpus figure cannot pick up a live run by iterating the
    obvious thing.
    """

    def __init__(
        self,
        grouped: dict[Source, tuple[JournalEntry, ...]],
        skipped: Skipped | None = None,
    ) -> None:
        self._grouped = {source: grouped.get(source, ()) for source in SOURCES}
        self.skipped = skipped or Skipped()

    @property
    def corpus(self) -> tuple[JournalEntry, ...]:
        """Runs against an accession in `frozen.json`. The scoreable population —
        scoreable by `map evaluate`, against a pinned vintage. Not here."""
        return self._grouped["corpus"]

    @property
    def edgar(self) -> tuple[JournalEntry, ...]:
        """`map run --from-edgar`. Outside the corpus, outside every scored set."""
        return self._grouped["edgar"]

    @property
    def news(self) -> tuple[JournalEntry, ...]:
        """`map run` over a news directory or RSS. Also outside the corpus."""
        return self._grouped["news"]

    @property
    def unknown(self) -> tuple[JournalEntry, ...]:
        """Manifests predating `document_source`. Not a claim either way."""
        return self._grouped["unknown"]

    def of(self, source: Source) -> tuple[JournalEntry, ...]:
        """One named population. There is deliberately no way to ask for all four."""
        return self._grouped[source]

    def populated(self) -> tuple[Source, ...]:
        """Which populations have entries — for a printer, not for arithmetic."""
        return tuple(source for source in SOURCES if self._grouped[source])


def _read_run(directory: Path, skipped: Counter[str]) -> tuple[Forecast, StoredManifest] | None:
    """Both artifacts, or nothing.

    A manifest is required, not optional. `runs/` holds pre-manifest captures from
    the first live forecasts, and a forecast without one has no `document_source`
    and no recorded anchor session — so it cannot be placed in a population, and
    placing it anywhere would be a guess.
    """
    forecast_path, manifest_path = directory / "forecast.json", directory / "manifest.json"
    if not (forecast_path.is_file() and manifest_path.is_file()):
        skipped["no_artifacts"] += 1
        return None
    try:
        forecast = Forecast.model_validate_json(forecast_path.read_text(encoding="utf-8"))
        manifest = StoredManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except (ValidationError, json.JSONDecodeError, UnicodeDecodeError):
        # Schema 1.x forecasts are in here too, and they parse as neither. Skipped
        # loudly rather than raised: one unreadable legacy directory must not stop
        # a listing of 800 readable ones.
        skipped["unreadable"] += 1
        _logger.warning("journal_unreadable_run", run=directory.name)
        return None
    return forecast, manifest


def _scenarios(forecast: Forecast) -> tuple[ScenarioLine, ...]:
    return tuple(
        ScenarioLine(
            name=name,
            probability_weight=scenario.probability_weight,
            price_return=scenario.price_return,
            annualised_vol=scenario.annualised_vol,
        )
        for name, scenario in (
            ("bullish", forecast.scenarios.bullish),
            ("base_case", forecast.scenarios.base_case),
            ("bearish", forecast.scenarios.bearish),
        )
    )


def _drift(window: PriceWindow, anchor: date, spot: float) -> AnchorDrift | None:
    """Whether the snapshot's anchor bar is the bar the forecast opened on.

    Two prices compared, which is not a score: nothing here reads a forecast's
    scenarios, and the import contract that keeps this module away from the scoring
    machinery is untouched. The tolerance is the one scoring uses, shared from
    `mapf.eval.window` rather than copied, so the two cannot drift apart.
    """
    bar = next((b for b in window.bars if b.date == anchor), None)
    if bar is None or abs(bar.close - spot) / spot <= SPOT_TOLERANCE:
        return None
    return AnchorDrift(recorded_spot=spot, snapshot_close=bar.close, ratio=bar.close / spot)


def _outcome(
    snapshot: PriceSnapshotIndex, forecast: Forecast, anchor: date, today: date
) -> tuple[Outcome | None, OutcomeStatus, AnchorDrift | None]:
    """The close the horizon landed on, retrieved from the snapshot, and why not.

    Three distinguishable answers, and the reason they are distinguished: a run
    whose ticker the snapshot never materialised looks exactly like a run whose
    horizon has not elapsed if both report "no close". The first is a gap in the
    stored series; the second is a fact about the calendar. Reporting the gap as
    the fact would be inventing an answer out of a missing file.
    """
    window: PriceWindow | None = snapshot.covering(forecast.ticker, anchor, anchor)
    if window is None:
        return None, "absent_from_snapshot", None
    drift = _drift(window, anchor, forecast.spot_price)
    try:
        bar = realised_bar(window, anchor, forecast.horizon_days)
    except WindowNotClosedError:
        return None, "window_open", drift
    except ScoringError:
        # The window spans the anchor by filename but holds no bar on or before it
        # — a gap in the stored series. Same answer as no window at all, because
        # the snapshot cannot reach this anchor either way. Typed rather than a
        # bare `except`, so a genuine bug here still surfaces as one.
        _logger.warning("journal_snapshot_gap", ticker=forecast.ticker, anchor=str(anchor))
        return None, "absent_from_snapshot", None
    return (
        Outcome(
            trading_date=bar.date,
            close=bar.close,
            provider=window.provider,
            adjustment=window.adjustment,
            snapshot=snapshot.vintage,
            retrieved_on=today,
        ),
        "closed",
        drift,
    )


def _relation(is_exhibit: bool | None, item: LedgerItem | None) -> CorpusRelation:
    """One value from two independent lookups, with the impossible pair excluded.

    A ledger entry wins outright: it names the item directly, which is a stronger
    statement than a document hash matching. If a run were somehow a ledger item
    whose document is NOT a frozen exhibit, the corpus and the ledger have diverged
    — reported as `ledger_item` here rather than invented into a fourth state,
    because scoring already refuses that case loudly and this is a listing.
    """
    if item is not None:
        return "ledger_item"
    if is_exhibit is None:
        return "unchecked"
    return "repeat_of_exhibit" if is_exhibit else "outside_corpus"


def _entries(
    runs_dir: Path,
    snapshot: PriceSnapshotIndex | None,
    today: date,
    limit: int | None,
    skipped: Counter[str],
    frozen_exhibits: frozenset[str] | None,
    ledger_items: Mapping[str, LedgerItem] | None,
) -> Iterator[JournalEntry]:
    directories = sorted((c for c in runs_dir.iterdir() if c.is_dir()), key=lambda c: c.name)
    read = [pair for d in directories if (pair := _read_run(d, skipped)) is not None]
    # Newest anchor first, so a `limit` keeps the recent end rather than whichever
    # UUIDs happened to sort low.
    read.sort(key=lambda pair: pair[1].prices.last_trading_date, reverse=True)
    for forecast, manifest in read[:limit] if limit is not None else read:
        anchor = manifest.prices.last_trading_date
        run_id = str(forecast.run_id)
        is_exhibit = (
            None
            if frozen_exhibits is None
            else any(doc in frozen_exhibits for doc in forecast.source_doc_ids)
        )
        item = None if ledger_items is None else ledger_items.get(run_id)
        relation = _relation(is_exhibit, item)
        outcome, status, drift = (
            (None, "not_requested", None)
            if snapshot is None
            else _outcome(snapshot, forecast, anchor, today)
        )
        yield JournalEntry(
            run_id=run_id,
            ticker=forecast.ticker,
            company_name=manifest.company_name,
            # The session the spot was read from, not `as_of`: `as_of` is a wall
            # clock (and for corpus items, the day after the filing), while the
            # anchor is the bar the forecast actually opened from.
            anchor_date=anchor,
            anchor_spot=forecast.spot_price,
            horizon_days=forecast.horizon_days,
            scenarios=_scenarios(forecast),
            document_source=manifest.document_source or "unknown",
            freeze_version=manifest.freeze_version,
            arm=manifest.arm,
            document_is_frozen_exhibit=is_exhibit,
            corpus_relation=relation,
            ledger_item=item,
            anchor_drift=drift,
            outcome=outcome,
            outcome_status=status,
        )


def read_journal(
    runs_dir: Path,
    *,
    snapshot: PriceSnapshotIndex | None = None,
    today: date,
    limit: int | None = None,
    frozen_exhibits: frozenset[str] | None = None,
    ledger_items: Mapping[str, LedgerItem] | None = None,
) -> Journal:
    """Every readable run under `runs_dir`, grouped by document source.

    `snapshot=None` reads the forecasts alone and reports every outcome as
    `not_requested` — never as an open window, which would be a claim about the
    calendar made from a question nobody asked. `limit` applies before grouping and
    after sorting, so it means "the N most recent runs", not "N of each kind".

    `frozen_exhibits` and `ledger_items` are both passed IN rather than loaded here:
    `mapf.corpus` sits above `mapf.eval`, and a journal that reached for a corpus or
    a ledger would break the layer contract and stop working in a checkout that has
    neither. Omit them and the membership field reads `None` and `corpus_relation`
    reads `"unchecked"` — nothing compared — rather than `False` and
    `"outside_corpus"`, which are claims.
    """
    if not runs_dir.is_dir():
        return Journal({})
    grouped: dict[Source, list[JournalEntry]] = {source: [] for source in SOURCES}
    counted: Counter[str] = Counter()
    for entry in _entries(runs_dir, snapshot, today, limit, counted, frozen_exhibits, ledger_items):
        grouped[entry.document_source].append(entry)
    return Journal(
        {source: tuple(entries) for source, entries in grouped.items()},
        Skipped(no_artifacts=counted["no_artifacts"], unreadable=counted["unreadable"]),
    )
