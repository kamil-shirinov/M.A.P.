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
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import structlog
from pydantic import BaseModel, ConfigDict, ValidationError

from mapf.core.models import Forecast, PriceWindow
from mapf.core.ports import MarketDataProvider
from mapf.eval.window import WindowNotClosedError, realised_bar

_logger = structlog.get_logger(__name__)

Source = Literal["corpus", "edgar", "news", "unknown"]
SOURCES: tuple[Source, ...] = ("corpus", "edgar", "news", "unknown")


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
    freeze_version: str | None = None


@dataclass(frozen=True)
class ScenarioLine:
    """One branch, exactly as the artifact stores it. No derived field."""

    name: str
    probability_weight: float
    price_return: float
    annualised_vol: float


@dataclass(frozen=True)
class Outcome:
    """What the price did, with the provenance of the series that says so.

    `provider` and `adjustment` travel with the close because a close without them
    is not comparable to anything (ADR 0003), and this one is fetched live rather
    than from the pinned scoring vintage — so it can move between two readings of
    the journal, and a reader has to be able to see which series it came from.
    """

    trading_date: date
    close: float
    provider: str
    adjustment: str


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
    anchor_date: date
    anchor_spot: float
    horizon_days: int
    scenarios: tuple[ScenarioLine, ...]
    document_source: Source
    freeze_version: str | None
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
    outcome: Outcome | None

    @property
    def window_elapsed(self) -> bool:
        return self.outcome is not None


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


def _outcome(
    market: MarketDataProvider, forecast: Forecast, anchor: date, today: date
) -> Outcome | None:
    """The close the horizon landed on, or `None` while the window is still open."""
    try:
        window: PriceWindow = market.get_ohlcv(forecast.ticker, anchor, today)
        bar = realised_bar(window, anchor, forecast.horizon_days)
    except WindowNotClosedError:
        return None
    except Exception:  # noqa: BLE001 - a listing must survive one bad ticker
        _logger.warning("journal_outcome_unavailable", ticker=forecast.ticker, anchor=str(anchor))
        return None
    return Outcome(
        trading_date=bar.date,
        close=bar.close,
        provider=window.provider,
        adjustment=window.adjustment,
    )


def _entries(
    runs_dir: Path,
    market: MarketDataProvider | None,
    today: date,
    limit: int | None,
    skipped: Counter[str],
    frozen_exhibits: frozenset[str] | None,
) -> Iterator[JournalEntry]:
    directories = sorted((c for c in runs_dir.iterdir() if c.is_dir()), key=lambda c: c.name)
    read = [pair for d in directories if (pair := _read_run(d, skipped)) is not None]
    # Newest anchor first, so a `limit` keeps the recent end rather than whichever
    # UUIDs happened to sort low.
    read.sort(key=lambda pair: pair[1].prices.last_trading_date, reverse=True)
    for forecast, manifest in read[:limit] if limit is not None else read:
        anchor = manifest.prices.last_trading_date
        yield JournalEntry(
            run_id=str(forecast.run_id),
            ticker=forecast.ticker,
            # The session the spot was read from, not `as_of`: `as_of` is a wall
            # clock (and for corpus items, the day after the filing), while the
            # anchor is the bar the forecast actually opened from.
            anchor_date=anchor,
            anchor_spot=forecast.spot_price,
            horizon_days=forecast.horizon_days,
            scenarios=_scenarios(forecast),
            document_source=manifest.document_source or "unknown",
            freeze_version=manifest.freeze_version,
            document_is_frozen_exhibit=(
                None
                if frozen_exhibits is None
                else any(doc in frozen_exhibits for doc in forecast.source_doc_ids)
            ),
            outcome=None if market is None else _outcome(market, forecast, anchor, today),
        )


def read_journal(
    runs_dir: Path,
    *,
    market: MarketDataProvider | None = None,
    today: date,
    limit: int | None = None,
    frozen_exhibits: frozenset[str] | None = None,
) -> Journal:
    """Every readable run under `runs_dir`, grouped by document source.

    `market=None` reads the forecasts alone and leaves every outcome open — the
    offline path, and the one tests use. `limit` applies before grouping and after
    sorting, so it means "the N most recent runs", not "N of each kind".

    `frozen_exhibits` is the set of `document_id`s the frozen corpus holds, passed
    IN rather than loaded here: `mapf.corpus` sits above `mapf.eval`, and a journal
    that reached for a corpus would both break the layer contract and stop working
    in a checkout that has no corpus. Omit it and the membership field reads `None`
    — nothing checked — rather than `False`.
    """
    if not runs_dir.is_dir():
        return Journal({})
    grouped: dict[Source, list[JournalEntry]] = {source: [] for source in SOURCES}
    counted: Counter[str] = Counter()
    for entry in _entries(runs_dir, market, today, limit, counted, frozen_exhibits):
        grouped[entry.document_source].append(entry)
    return Journal(
        {source: tuple(entries) for source, entries in grouped.items()},
        Skipped(no_artifacts=counted["no_artifacts"], unreadable=counted["unreadable"]),
    )
