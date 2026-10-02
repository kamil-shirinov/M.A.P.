"""The run journal: what was forecast, what happened, and what it refuses to be.

Two of these tests are worth more than the rest. One pins that no entry can be
turned into a score by reaching for an attribute; the other pins that corpus and
live runs have no shared accessor to be pooled through. Both are properties of the
types, so they fail on the change rather than on a review someone skips.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from mapf.core.models import (
    Bar,
    DividendWindow,
    Forecast,
    ModelVersions,
    PriceWindow,
    Scenario,
    ScenarioSet,
)
from mapf.core.ports import SamplingParams
from mapf.eval.journal import (
    SOURCES,
    Journal,
    JournalEntry,
    LedgerItem,
    Outcome,
    read_journal,
    relate_to_frozen,
)
from mapf.pipeline.manifest import (
    AgentRecord,
    PriceProvenance,
    RunManifest,
)

ANCHOR = date(2026, 8, 3)


def _scenarios() -> ScenarioSet:
    return ScenarioSet(
        bullish=Scenario(
            justification="A sufficiently long justification for the bullish branch.",
            probability_weight=0.25,
            price_return=0.045,
            annualised_vol=0.30,
        ),
        base_case=Scenario(
            justification="A sufficiently long justification for the base branch.",
            probability_weight=0.60,
            price_return=0.008,
            annualised_vol=0.28,
        ),
        bearish=Scenario(
            justification="A sufficiently long justification for the bearish branch.",
            probability_weight=0.15,
            price_return=-0.082,
            annualised_vol=0.41,
        ),
    )


def _write_run(
    runs_dir: Path,
    *,
    ticker: str = "AAPL",
    source: str | None = "corpus",
    arm: str | None = None,
    anchor: date = ANCHOR,
    horizon: int = 5,
    freeze_version: str | None = "2.4.0",
    manifest: bool = True,
    document_accession: str | None = None,
    doc_id: str = "sha256:" + "a" * 64,
) -> str:
    run_id = uuid4()
    directory = runs_dir / str(run_id)
    directory.mkdir(parents=True)
    forecast = Forecast(
        run_id=run_id,
        ticker=ticker,
        as_of=datetime.combine(anchor, datetime.min.time(), tzinfo=UTC) + timedelta(days=1),
        horizon_days=horizon,
        spot_price=201.0,
        source_doc_ids=(doc_id,),
        model_versions=ModelVersions(intake="fp-i", analyst="fp-a", structuralist="fp-s"),
        scenarios=_scenarios(),
    )
    (directory / "forecast.json").write_text(forecast.model_dump_json(), encoding="utf-8")
    if manifest:
        record = RunManifest(
            forecast_schema_version="2.0.0",
            run_id=run_id,
            ticker=ticker,
            as_of=forecast.as_of,
            horizon_days=horizon,
            spot_price=201.0,
            source_doc_ids=forecast.source_doc_ids,
            agents=(
                AgentRecord(
                    alias="intake",
                    model_id="llama",
                    fingerprint="fp-i",
                    fingerprint_source="tag",
                    sampling=SamplingParams(temperature=0.0),
                    template_name="intake",
                    template_version="v1",
                    template_sha256="0" * 64,
                ),
            ),
            prices=PriceProvenance(
                provider="yfinance",
                adjustment="split_adjusted",
                fetched_on=anchor,
                window_start=anchor - timedelta(days=30),
                window_end=anchor,
                last_trading_date=anchor,
                bars=20,
            ),
            dividends=DividendWindow(start=anchor, end=anchor, known=False, source="none"),
            document_source=source,  # type: ignore[arg-type]
            document_accession=document_accession,
            arm=arm,
            freeze_version=freeze_version,
            package_version="0.1.0",
            python_version="3.12.0",
        )
        (directory / "manifest.json").write_text(record.model_dump_json(), encoding="utf-8")
    return str(run_id)


VINTAGE = date(2026, 9, 5)


class _Snapshot:
    """A stored vintage holding a series for some tickers and not others."""

    def __init__(self, sessions: int = 30, holds: tuple[str, ...] | None = None) -> None:
        self._sessions = sessions
        self._holds = holds
        self.asked: list[str] = []

    @property
    def vintage(self) -> date:
        return VINTAGE

    def covering(self, ticker: str, start: date, end: date) -> PriceWindow | None:
        self.asked.append(ticker)
        if self._holds is not None and ticker not in self._holds:
            return None
        return PriceWindow(
            ticker=ticker,
            provider="yfinance",
            adjustment="split_adjusted",
            bars=tuple(
                Bar(
                    date=ANCHOR + timedelta(days=i),
                    open=200.0 + i,
                    high=203.0 + i,
                    low=199.0 + i,
                    close=201.0 + i,
                    volume=1_000,
                )
                for i in range(self._sessions)
            ),
        )


# ---------------------------------------------------------------------------
# The two constraints
# ---------------------------------------------------------------------------
def test_an_entry_offers_no_way_to_turn_a_forecast_and_an_outcome_into_a_score() -> None:
    """`runs/` is a population defined after the fact — by curiosity, retries and
    interrupted evenings. A number computed over it would be real arithmetic on an
    unreal sample, and it would be quoted. The entry carries both sides and
    combines them nowhere."""
    carried = set(JournalEntry.__dataclass_fields__)
    derived = {name for name in dir(JournalEntry) if not name.startswith("_")} - carried

    assert carried == {
        "run_id",
        "ticker",
        # Recorded at run time, not resolved here: the journal looks names up in
        # the frozen 120, so a run outside the corpus had none anywhere.
        "company_name",
        "anchor_date",
        # Read off the run's own trace: when it was made. A time, not a result, so
        # it combines nothing across the two sides either.
        "made_at",
        "anchor_spot",
        # From what the run recorded about WHEN it read its price. Not derived from
        # the outcome, so it combines nothing across the two sides.
        "price_kind",
        "horizon_days",
        "scenarios",
        "document_source",
        "freeze_version",
        "arm",
        "document_is_frozen_exhibit",
        "corpus_relation",
        "ledger_item",
        "anchor_drift",
        "outcome",
        "outcome_status",
    }
    # It computes NOTHING. `outcome_status` is recorded per run by the reader, not
    # derived here, so there is no member at all that reads both sides.
    assert derived == set()


def test_the_journal_has_no_pooled_accessor_to_concatenate_populations() -> None:
    """Separability by construction rather than by discipline: an --from-edgar run
    is outside frozen.json, and a combined tuple would put it one `sum()` away from
    a corpus statistic."""
    journal = Journal({})

    assert not hasattr(journal, "entries")
    assert not hasattr(journal, "all")
    with pytest.raises(TypeError):
        list(journal)  # type: ignore[call-overload]
    with pytest.raises(TypeError):
        len(journal)  # type: ignore[arg-type]


def test_a_live_run_never_lands_in_the_corpus_population(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    corpus_id = _write_run(runs, source="corpus", ticker="AAA")
    edgar_id = _write_run(runs, source="edgar", ticker="BBB", freeze_version=None)
    news_id = _write_run(runs, source="news", ticker="CCC", freeze_version=None)

    journal = read_journal(runs, today=date(2026, 9, 8))

    assert [e.run_id for e in journal.corpus] == [corpus_id]
    assert [e.run_id for e in journal.edgar] == [edgar_id]
    assert [e.run_id for e in journal.news] == [news_id]


def test_a_manifest_predating_the_field_is_its_own_population(tmp_path: Path) -> None:
    """Not a synonym for either. `None` was never a claim about the source."""
    runs = tmp_path / "runs"
    unknown_id = _write_run(runs, source=None)

    journal = read_journal(runs, today=date(2026, 9, 8))

    assert [e.run_id for e in journal.unknown] == [unknown_id]
    assert journal.corpus == ()


# ---------------------------------------------------------------------------
# What it reads
# ---------------------------------------------------------------------------
def test_each_entry_carries_the_anchor_and_the_three_scenarios(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_run(runs)

    entry = read_journal(runs, today=date(2026, 9, 8)).corpus[0]

    assert entry.ticker == "AAPL"
    assert entry.anchor_date == ANCHOR
    assert entry.anchor_spot == 201.0
    assert [line.name for line in entry.scenarios] == ["bullish", "base_case", "bearish"]
    assert [line.price_return for line in entry.scenarios] == [0.045, 0.008, -0.082]
    assert [line.probability_weight for line in entry.scenarios] == [0.25, 0.60, 0.15]


def test_an_entry_says_when_its_run_was_made_from_its_trace(tmp_path: Path) -> None:
    """Made on the 30th before the close, anchored on the 29th's close: the two are
    different days, and the entry carries both. The time is the trace's first
    event, which the run stamped as it happened."""
    from mapf.cli.commands.runs import as_dict
    from mapf.pipeline.trace import JsonlTrace

    runs = tmp_path / "runs"
    run_id = _write_run(runs)
    made = datetime(2026, 9, 30, 12, 21, 11, tzinfo=UTC)
    trace = JsonlTrace(runs / run_id / "trace.jsonl", now=lambda: made)
    trace.record(stage="intake")
    trace.close()

    entry = read_journal(runs, today=date(2026, 9, 8)).corpus[0]

    assert entry.made_at == made
    assert entry.anchor_date == ANCHOR, "the anchor is untouched"
    assert as_dict(entry)["made_at"] == "2026-09-30T12:21:11+00:00"


def test_a_run_with_no_trace_has_no_made_time(tmp_path: Path) -> None:
    """63 run directories hold no trace and 23 an empty one. None, not a guess
    from `as_of` — which for a corpus run is months before the run was made."""
    from mapf.cli.commands.runs import as_dict

    runs = tmp_path / "runs"
    _write_run(runs)
    entry = read_journal(runs, today=date(2026, 9, 8)).corpus[0]
    assert entry.made_at is None
    assert as_dict(entry)["made_at"] is None


def test_the_anchor_is_the_session_the_spot_was_read_from_not_as_of(tmp_path: Path) -> None:
    """`as_of` is the day after the filing for a corpus item, and a wall clock for a
    live one. Neither is the bar the forecast opened from."""
    runs = tmp_path / "runs"
    _write_run(runs)

    entry = read_journal(runs, today=date(2026, 9, 8)).corpus[0]

    assert entry.anchor_date == ANCHOR
    assert entry.anchor_date != date(2026, 8, 4)


def test_an_elapsed_window_records_the_close_it_landed_on(tmp_path: Path) -> None:
    """Attributed, not asserted: the vintage it came from and the day it was read
    travel with the value, so it can never be mistaken for something stored."""
    runs = tmp_path / "runs"
    _write_run(runs, horizon=5)

    entry = read_journal(runs, snapshot=_Snapshot(), today=date(2026, 9, 8)).corpus[0]

    assert entry.outcome_status == "closed"
    assert entry.outcome == Outcome(
        trading_date=ANCHOR + timedelta(days=5),
        close=206.0,
        provider="yfinance",
        adjustment="split_adjusted",
        snapshot=VINTAGE,
        retrieved_on=date(2026, 9, 8),
    )


def test_an_open_window_is_reported_as_open_not_dropped(tmp_path: Path) -> None:
    """A listing that silently omitted unfinished runs would shrink with the
    calendar and look like a shorter history than it is."""
    runs = tmp_path / "runs"
    _write_run(runs, horizon=60)

    entry = read_journal(runs, snapshot=_Snapshot(sessions=10), today=date(2026, 9, 8)).corpus[0]

    assert entry.outcome_status == "window_open"
    assert entry.outcome is None


def test_without_a_snapshot_nothing_is_claimed_about_the_horizon(tmp_path: Path) -> None:
    """Not "open". Nobody asked, and reporting that as an unelapsed window would be
    a statement about the calendar derived from a question never put."""
    runs = tmp_path / "runs"
    _write_run(runs)

    entry = read_journal(runs, snapshot=None, today=date(2026, 9, 8)).corpus[0]

    assert entry.outcome_status == "not_requested"
    assert entry.outcome is None


def test_a_ticker_the_snapshot_does_not_hold_says_so_rather_than_vanishing(
    tmp_path: Path,
) -> None:
    """The row stays, with the reason. A missing series and an unelapsed horizon
    are different facts, and only one of them is about the calendar."""
    runs = tmp_path / "runs"
    _write_run(runs, ticker="ZZZZ")

    entry = read_journal(runs, snapshot=_Snapshot(holds=("AAPL",)), today=date(2026, 9, 8)).corpus[
        0
    ]

    assert entry.outcome_status == "absent_from_snapshot"
    assert entry.outcome is None
    assert entry.ticker == "ZZZZ"


def test_a_gap_in_the_stored_series_is_reported_as_absent_not_as_open(
    tmp_path: Path,
) -> None:
    """A window whose filename spans the anchor but whose bars start after it. The
    snapshot cannot reach this anchor, which is the same answer as holding no
    window — and emphatically not "the horizon has not elapsed"."""

    class _Gapped:
        vintage = VINTAGE

        def covering(self, ticker: str, start: date, end: date) -> PriceWindow:
            return PriceWindow(
                ticker=ticker,
                provider="yfinance",
                adjustment="split_adjusted",
                bars=tuple(
                    Bar(
                        date=ANCHOR + timedelta(days=30 + i),
                        open=200.0,
                        high=203.0,
                        low=199.0,
                        close=201.0,
                        volume=1,
                    )
                    for i in range(10)
                ),
            )

    runs = tmp_path / "runs"
    _write_run(runs)

    entry = read_journal(runs, snapshot=_Gapped(), today=date(2026, 9, 8)).corpus[0]

    assert entry.outcome_status == "absent_from_snapshot"


# ---------------------------------------------------------------------------
# What it skips
# ---------------------------------------------------------------------------
def test_a_run_without_a_manifest_is_skipped_rather_than_placed_by_guess(
    tmp_path: Path,
) -> None:
    """`runs/` holds pre-manifest captures. Without a manifest there is no
    document_source and no recorded anchor session, so any placement is invention."""
    runs = tmp_path / "runs"
    _write_run(runs, manifest=False)

    assert read_journal(runs, today=date(2026, 9, 8)).populated() == ()


def test_an_unparseable_forecast_does_not_stop_the_readable_ones(tmp_path: Path) -> None:
    """Schema 1.x artifacts are still in there and parse as neither."""
    runs = tmp_path / "runs"
    good = _write_run(runs)
    broken = runs / "not-a-uuid"
    broken.mkdir()
    (broken / "forecast.json").write_text(json.dumps({"schema_version": "1.0.0"}), encoding="utf-8")
    (broken / "manifest.json").write_text("{}", encoding="utf-8")

    journal = read_journal(runs, today=date(2026, 9, 8))

    assert [e.run_id for e in journal.corpus] == [good]


def test_a_missing_runs_directory_is_an_empty_journal_not_a_failure(tmp_path: Path) -> None:
    assert read_journal(tmp_path / "absent", today=date(2026, 9, 8)).populated() == ()


def test_a_stray_file_beside_the_run_directories_is_ignored(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "README.md").write_text("not a run", encoding="utf-8")
    _write_run(runs)

    assert len(read_journal(runs, today=date(2026, 9, 8)).corpus) == 1


# ---------------------------------------------------------------------------
# Ordering and limit
# ---------------------------------------------------------------------------
def test_the_limit_keeps_the_most_recent_anchors_not_the_lowest_uuids(
    tmp_path: Path,
) -> None:
    runs = tmp_path / "runs"
    _write_run(runs, anchor=date(2026, 1, 5), ticker="OLD")
    recent = _write_run(runs, anchor=date(2026, 8, 3), ticker="NEW")

    journal = read_journal(runs, today=date(2026, 9, 8), limit=1)

    assert [e.run_id for e in journal.corpus] == [recent]


def test_the_limit_is_taken_before_grouping_so_it_means_n_runs_not_n_of_each(
    tmp_path: Path,
) -> None:
    runs = tmp_path / "runs"
    _write_run(runs, anchor=date(2026, 8, 3), source="corpus")
    _write_run(runs, anchor=date(2026, 7, 3), source="edgar", freeze_version=None)

    journal = read_journal(runs, today=date(2026, 9, 8), limit=1)

    assert len(journal.corpus) == 1
    assert journal.edgar == ()


def test_every_source_name_is_reachable_through_of() -> None:
    journal = Journal({})
    assert all(journal.of(source) == () for source in SOURCES)
    assert SOURCES == ("corpus", "edgar", "news", "unknown")


# ---------------------------------------------------------------------------
# What it could not read
# ---------------------------------------------------------------------------
def test_directories_it_cannot_place_are_counted_not_dropped(tmp_path: Path) -> None:
    """Silent attrition is the failure mode this project treats as a defect. 47 of
    826 real run directories are unreadable, and a listing that showed 779 with no
    remark would read as a complete history."""
    runs = tmp_path / "runs"
    _write_run(runs)
    _write_run(runs, manifest=False)
    broken = runs / "legacy"
    broken.mkdir()
    (broken / "forecast.json").write_text(json.dumps({"schema_version": "1.0.0"}), encoding="utf-8")
    (broken / "manifest.json").write_text("{}", encoding="utf-8")

    journal = read_journal(runs, today=date(2026, 9, 8))

    assert len(journal.corpus) == 1
    assert journal.skipped.no_artifacts == 1
    assert journal.skipped.unreadable == 1


def test_the_skipped_count_is_taken_before_the_limit(tmp_path: Path) -> None:
    """It answers "what is here that this cannot show", which a limit must not
    change — otherwise `--limit 1` would report a clean directory."""
    runs = tmp_path / "runs"
    _write_run(runs)
    _write_run(runs, manifest=False)

    assert read_journal(runs, today=date(2026, 9, 8), limit=1).skipped.no_artifacts == 1


def test_a_manifest_from_an_older_format_version_still_reads(tmp_path: Path) -> None:
    """`RunManifest` pins `manifest_version` to a Literal, so bumping it to 1.8.0
    made all 831 stored 1.7.0 manifests fail to validate. That is right for a
    writer and unusable for a reader, which is why the journal has its own."""
    runs = tmp_path / "runs"
    run_id = _write_run(runs)
    path = runs / run_id / "manifest.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["manifest_version"] = "1.2.0"
    stored["a_field_this_version_never_had"] = True
    path.write_text(json.dumps(stored), encoding="utf-8")

    journal = read_journal(runs, today=date(2026, 9, 8))

    assert len(journal.corpus) == 1
    assert journal.skipped.unreadable == 0


def test_a_manifest_missing_the_anchor_is_unreadable_rather_than_guessed(
    tmp_path: Path,
) -> None:
    """The reader is permissive about fields it does not use and strict about the
    four it does. Without `prices.last_trading_date` there is no anchor, and an
    invented one would re-time the horizon."""
    runs = tmp_path / "runs"
    run_id = _write_run(runs)
    path = runs / run_id / "manifest.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    del stored["prices"]
    path.write_text(json.dumps(stored), encoding="utf-8")

    journal = read_journal(runs, today=date(2026, 9, 8))

    assert journal.populated() == ()
    assert journal.skipped.unreadable == 1


# ---------------------------------------------------------------------------
# Corpus membership as a positive check
# ---------------------------------------------------------------------------
def _doc_id_of(runs: Path, run_id: str) -> str:
    body = json.loads((runs / run_id / "forecast.json").read_text(encoding="utf-8"))
    return str(body["source_doc_ids"][0])


def test_membership_is_an_equality_test_between_two_frozen_records(tmp_path: Path) -> None:
    """Not an inference from absence. `frozen.json` records the document_id of
    every exhibit; a forecast records the ids of the documents it read."""
    runs = tmp_path / "runs"
    run_id = _write_run(runs)

    journal = read_journal(
        runs, today=date(2026, 9, 8), frozen_exhibits=frozenset({_doc_id_of(runs, run_id)})
    )

    assert journal.corpus[0].document_is_frozen_exhibit is True


def test_a_document_the_corpus_does_not_hold_reads_false(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_run(runs)

    journal = read_journal(runs, today=date(2026, 9, 8), frozen_exhibits=frozenset({"sha256:zz"}))

    assert journal.corpus[0].document_is_frozen_exhibit is False


def test_no_map_means_unchecked_not_false(tmp_path: Path) -> None:
    """False is a claim. The journal must work in a checkout with no corpus, and
    saying "not a frozen exhibit" there would be an answer it never computed."""
    runs = tmp_path / "runs"
    _write_run(runs)

    assert read_journal(runs, today=date(2026, 9, 8)).corpus[0].document_is_frozen_exhibit is None


def test_the_field_does_not_touch_what_the_writer_recorded(tmp_path: Path) -> None:
    """An --from-edgar run whose filing the corpus happens to hold: the document
    really is a corpus exhibit and the run really is not a corpus run. Both are
    reported, in their own fields, and neither overwrites the other."""
    runs = tmp_path / "runs"
    run_id = _write_run(runs, source="edgar", freeze_version=None)

    entry = read_journal(
        runs, today=date(2026, 9, 8), frozen_exhibits=frozenset({_doc_id_of(runs, run_id)})
    ).edgar[0]

    assert entry.document_is_frozen_exhibit is True
    assert entry.document_source == "edgar"
    assert entry.freeze_version is None


def test_membership_never_moves_a_run_between_populations(tmp_path: Path) -> None:
    """It is a derived label, not a classifier. Grouping stays on the recorded
    field, so a matching document cannot promote a live run into the corpus set."""
    runs = tmp_path / "runs"
    run_id = _write_run(runs, source="edgar", freeze_version=None)

    journal = read_journal(
        runs, today=date(2026, 9, 8), frozen_exhibits=frozenset({_doc_id_of(runs, run_id)})
    )

    assert journal.corpus == ()
    assert len(journal.edgar) == 1


# ---------------------------------------------------------------------------
# Experimental arms
# ---------------------------------------------------------------------------
def test_an_ablation_arm_is_visible_in_the_entry(tmp_path: Path) -> None:
    """Arm A replays the corpus from cache: its forecasts are byte-identical to
    the corpus runs apart from run_id. A directory is a convention and does not
    survive being copied or pointed at; the artifact has to say what it is."""
    runs = tmp_path / "runs"
    _write_run(runs, arm="A")

    assert read_journal(runs, today=date(2026, 9, 8)).corpus[0].arm == "A"


def test_a_run_that_is_not_an_experiment_reports_no_arm(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_run(runs)

    assert read_journal(runs, today=date(2026, 9, 8)).corpus[0].arm is None


def test_an_arm_does_not_move_a_run_between_populations(tmp_path: Path) -> None:
    """Orthogonal to where the document came from. An arm A replay reads a corpus
    exhibit and stays in the corpus population, labelled."""
    runs = tmp_path / "runs"
    _write_run(runs, arm="A", source="corpus")

    journal = read_journal(runs, today=date(2026, 9, 8))

    assert len(journal.corpus) == 1
    assert journal.corpus[0].arm == "A"


# ---------------------------------------------------------------------------
# corpus_relation — the three cases a front end has to tell apart
# ---------------------------------------------------------------------------
def test_a_ledger_entry_makes_a_run_a_panel_item(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run_id = _write_run(runs)
    item = LedgerItem(ticker="AAPL", band="clean", filing_date=date(2026, 8, 2))

    entry = read_journal(
        runs,
        today=date(2026, 9, 8),
        frozen_exhibits=frozenset({_doc_id_of(runs, run_id)}),
        ledger_items={run_id: item},
    ).corpus[0]

    assert entry.corpus_relation == "ledger_item"
    assert entry.ledger_item == item


def test_a_frozen_exhibit_with_no_ledger_entry_is_a_repeat(tmp_path: Path) -> None:
    """The 74 runs that would otherwise be indistinguishable from panel items:
    re-runs, post-band repeats, ablation replays of the same document."""
    runs = tmp_path / "runs"
    run_id = _write_run(runs)

    entry = read_journal(
        runs,
        today=date(2026, 9, 8),
        frozen_exhibits=frozenset({_doc_id_of(runs, run_id)}),
        ledger_items={},
    ).corpus[0]

    assert entry.corpus_relation == "repeat_of_exhibit"
    assert entry.ledger_item is None
    assert entry.document_is_frozen_exhibit is True


def test_a_document_the_corpus_never_froze_is_outside_it(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_run(runs)

    entry = read_journal(
        runs, today=date(2026, 9, 8), frozen_exhibits=frozenset(), ledger_items={}
    ).corpus[0]

    assert entry.corpus_relation == "outside_corpus"


def test_supplying_neither_map_is_unchecked_not_outside(tmp_path: Path) -> None:
    """ "Outside the corpus" is a claim. Nothing was compared."""
    runs = tmp_path / "runs"
    _write_run(runs)

    assert read_journal(runs, today=date(2026, 9, 8)).corpus[0].corpus_relation == "unchecked"


def test_the_band_and_filing_date_are_carried_not_re_derived(tmp_path: Path) -> None:
    """A corpus forecast is dated the day AFTER the filing it reads. Reconstructing
    the filing date from the anchor is off by a day, and matching on it silently
    matches nothing — the trap `Loaded` documents on the scoring side."""
    runs = tmp_path / "runs"
    run_id = _write_run(runs, anchor=date(2026, 8, 3))

    entry = read_journal(
        runs,
        today=date(2026, 9, 8),
        ledger_items={
            run_id: LedgerItem(ticker="AAPL", band="ambiguous", filing_date=date(2026, 7, 31))
        },
    ).corpus[0]

    assert entry.ledger_item is not None
    assert entry.ledger_item.band == "ambiguous"
    assert entry.ledger_item.filing_date == date(2026, 7, 31)
    # Emphatically not the anchor, and not the anchor minus one.
    assert entry.ledger_item.filing_date != entry.anchor_date


def test_a_ledger_entry_wins_over_a_document_that_does_not_match(tmp_path: Path) -> None:
    """The pair that cannot happen: a ledger item whose document is not a frozen
    exhibit means the ledger and the corpus have diverged. Reported as the ledger
    says rather than invented into a fourth state — scoring already refuses that
    case loudly, and this is a listing."""
    runs = tmp_path / "runs"
    run_id = _write_run(runs)

    entry = read_journal(
        runs,
        today=date(2026, 9, 8),
        frozen_exhibits=frozenset(),
        ledger_items={
            run_id: LedgerItem(ticker="AAPL", band="clean", filing_date=date(2026, 8, 2))
        },
    ).corpus[0]

    assert entry.corpus_relation == "ledger_item"
    assert entry.document_is_frozen_exhibit is False


def test_corpus_relation_never_moves_a_run_between_populations(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run_id = _write_run(runs, source="edgar", freeze_version=None)

    journal = read_journal(
        runs,
        today=date(2026, 9, 8),
        ledger_items={
            run_id: LedgerItem(ticker="AAPL", band="clean", filing_date=date(2026, 8, 2))
        },
    )

    assert journal.corpus == ()
    assert journal.edgar[0].corpus_relation == "ledger_item"


# ---------------------------------------------------------------------------
# Anchor drift — a guard firing where the consumer can see it
# ---------------------------------------------------------------------------
class _Rebased:
    """A snapshot re-based by a corporate action after the run was written."""

    vintage = VINTAGE

    def __init__(self, factor: float = 1.012) -> None:
        self._factor = factor

    def covering(self, ticker: str, start: date, end: date) -> PriceWindow:
        return PriceWindow(
            ticker=ticker,
            provider="yfinance",
            adjustment="split_adjusted",
            bars=tuple(
                Bar(
                    date=ANCHOR + timedelta(days=i),
                    open=(200.0 + i) * self._factor,
                    high=(203.0 + i) * self._factor,
                    low=(199.0 + i) * self._factor,
                    close=(201.0 + i) * self._factor,
                    volume=1_000,
                )
                for i in range(30)
            ),
        )


def test_an_anchor_the_snapshot_disagrees_with_is_reported(tmp_path: Path) -> None:
    """The corpus holds a 1.012 split. After it, the anchor bar in a later snapshot
    is not the bar the forecast opened on, and scoring refuses the item — but the
    journal is not scoring and would otherwise publish the outcome silently."""
    runs = tmp_path / "runs"
    _write_run(runs, horizon=5)

    entry = read_journal(runs, snapshot=_Rebased(), today=date(2026, 9, 8)).corpus[0]

    assert entry.anchor_drift is not None
    assert entry.anchor_drift.recorded_spot == 201.0
    assert entry.anchor_drift.ratio == pytest.approx(1.012)


def test_drift_does_not_suppress_the_outcome(tmp_path: Path) -> None:
    """An outcome that exists and is not comparable is a different fact from an
    outcome that does not exist. The row is never omitted (ADR 0035)."""
    runs = tmp_path / "runs"
    _write_run(runs, horizon=5)

    entry = read_journal(runs, snapshot=_Rebased(), today=date(2026, 9, 8)).corpus[0]

    assert entry.outcome_status == "closed"
    assert entry.outcome is not None


def test_an_agreeing_anchor_reports_no_drift(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_run(runs, horizon=5)

    entry = read_journal(runs, snapshot=_Snapshot(), today=date(2026, 9, 8)).corpus[0]

    assert entry.anchor_drift is None


def test_drift_is_checked_on_an_open_window_too(tmp_path: Path) -> None:
    """It is a fact about the price series, not about the horizon."""
    runs = tmp_path / "runs"
    _write_run(runs, horizon=60)

    entry = read_journal(runs, snapshot=_Rebased(), today=date(2026, 9, 8)).corpus[0]

    assert entry.outcome_status == "window_open"
    assert entry.anchor_drift is not None


def test_drift_is_reported_for_runs_no_scoring_pass_ever_attempted(tmp_path: Path) -> None:
    """Three of the nine real drifted runs are a repeat and two outside the corpus.
    A field named "scoring declined this" would be false for all three, which is why
    it is named for the drift instead."""
    runs = tmp_path / "runs"
    _write_run(runs, source="edgar", freeze_version=None)

    entry = read_journal(runs, snapshot=_Rebased(), today=date(2026, 9, 8)).edgar[0]

    assert entry.corpus_relation == "unchecked"
    assert entry.anchor_drift is not None


def test_noise_below_the_scoring_tolerance_is_not_drift(tmp_path: Path) -> None:
    """The same tolerance scoring uses, shared rather than copied, so a run this
    calls clean is one scoring would accept."""
    runs = tmp_path / "runs"
    _write_run(runs, horizon=5)

    entry = read_journal(runs, snapshot=_Rebased(1 + 1e-6), today=date(2026, 9, 8)).corpus[0]

    assert entry.anchor_drift is None


# ---------------------------------------------------------------------------
# One rule for "is this document in the corpus", shared with the live page
# ---------------------------------------------------------------------------
HELD = "sha256:" + "a" * 64
RE_FETCHED = "sha256:" + "c" * 64  # the same filing, arriving as different bytes
ACCESSION = "0000320193-26-000018"


@pytest.mark.parametrize(
    ("documents", "accession", "frozen_documents", "frozen_accessions", "expected"),
    [
        # Nothing was compared: not "no match".
        ([HELD], ACCESSION, None, None, "unchecked"),
        # The document id is the primary test.
        ([HELD], None, frozenset({HELD}), frozenset(), "repeat_of_exhibit"),
        ([HELD], "other", frozenset({HELD}), frozenset({ACCESSION}), "repeat_of_exhibit"),
        # The accession is the fallback: same filing, different bytes.
        ([RE_FETCHED], ACCESSION, frozenset({HELD}), frozenset({ACCESSION}), "repeat_of_exhibit"),
        # Neither matches.
        ([RE_FETCHED], "other", frozenset({HELD}), frozenset({ACCESSION}), "outside_corpus"),
        # A run that never recorded its accession can only be judged by its hash, and
        # a different hash then reads outside: the limit of what it knows.
        ([RE_FETCHED], None, frozenset({HELD}), frozenset({ACCESSION}), "outside_corpus"),
        # Only one side of the freeze was supplied.
        ([RE_FETCHED], ACCESSION, None, frozenset({ACCESSION}), "repeat_of_exhibit"),
        ([RE_FETCHED], "other", None, frozenset({ACCESSION}), "outside_corpus"),
        ([RE_FETCHED], ACCESSION, frozenset({HELD}), None, "outside_corpus"),
        ([], ACCESSION, frozenset({HELD}), frozenset({ACCESSION}), "repeat_of_exhibit"),
    ],
)
def test_the_one_rule_for_relating_a_document_to_the_frozen_corpus(
    documents: list[str],
    accession: str | None,
    frozen_documents: frozenset[str] | None,
    frozen_accessions: frozenset[str] | None,
    expected: str,
) -> None:
    assert (
        relate_to_frozen(
            document_ids=documents,
            accession=accession,
            frozen_documents=frozen_documents,
            frozen_accessions=frozen_accessions,
        )
        == expected
    )


def _live_entry(
    tmp_path: Path, *, accession: str | None, frozen_accessions: frozenset[str] | None
) -> JournalEntry:
    runs = tmp_path / "runs"
    _write_run(
        runs,
        source="edgar",
        freeze_version=None,
        doc_id=RE_FETCHED,
        document_accession=accession,
    )
    return read_journal(
        runs,
        today=date(2026, 9, 8),
        frozen_exhibits=frozenset({HELD}),
        frozen_accessions=frozen_accessions,
    ).edgar[0]


def test_a_live_run_of_a_frozen_filing_reads_repeat_by_its_accession(tmp_path: Path) -> None:
    """The defect. The journal listed this run as outside the corpus while the page
    that made it called the same filing a repeat: the hash differed and only the
    accession said which filing it was."""
    entry = _live_entry(tmp_path, accession=ACCESSION, frozen_accessions=frozenset({ACCESSION}))

    assert entry.corpus_relation == "repeat_of_exhibit"
    assert entry.document_is_frozen_exhibit is True
    # What the writer recorded is untouched: it is still not a corpus run.
    assert entry.document_source == "edgar"
    assert entry.freeze_version is None


def test_a_live_run_with_no_recorded_accession_is_judged_by_its_hash_alone(
    tmp_path: Path,
) -> None:
    """Every run made before the accession was recorded. It stays outside, because
    that is all the hash can say, and the limit is named in the code rather than
    papered over."""
    entry = _live_entry(tmp_path, accession=None, frozen_accessions=frozenset({ACCESSION}))

    assert entry.corpus_relation == "outside_corpus"


def test_without_the_accessions_the_journal_behaves_as_it_always_did(tmp_path: Path) -> None:
    entry = _live_entry(tmp_path, accession=ACCESSION, frozen_accessions=None)

    assert entry.corpus_relation == "outside_corpus"


def test_a_ledger_entry_still_wins_over_a_document_lookup(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run_id = _write_run(
        runs, source="edgar", freeze_version=None, doc_id=RE_FETCHED, document_accession=ACCESSION
    )

    entry = read_journal(
        runs,
        today=date(2026, 9, 8),
        frozen_exhibits=frozenset({HELD}),
        frozen_accessions=frozenset({ACCESSION}),
        ledger_items={run_id: LedgerItem("AAPL", "clean", date(2026, 7, 30))},
    ).edgar[0]

    assert entry.corpus_relation == "ledger_item"


@pytest.mark.parametrize(
    ("document", "accession", "documents", "accessions"),
    [
        (HELD, ACCESSION, {HELD}, {ACCESSION}),  # held by hash
        (RE_FETCHED, ACCESSION, {HELD}, {ACCESSION}),  # held only by accession
        (RE_FETCHED, "other", {HELD}, {ACCESSION}),  # not held
        (RE_FETCHED, ACCESSION, set(), set()),  # no freeze loaded: nothing compared
    ],
)
def test_the_journal_and_the_live_result_say_the_same_thing(
    tmp_path: Path, document: str, accession: str, documents: set[str], accessions: set[str]
) -> None:
    """The requirement, as a test: the page's lookup (`Freeze`) and the journal's
    row for the same run, over the same frozen sets, give one answer."""
    from mapf.serve.analyse import Freeze

    runs = tmp_path / "runs"
    _write_run(
        runs, source="edgar", freeze_version=None, doc_id=document, document_accession=accession
    )
    shown = Freeze(document_ids=frozenset(documents), accessions=frozenset(accessions)).relate(
        document_id=document, accession=accession
    )

    listed = read_journal(
        runs,
        today=date(2026, 9, 8),
        frozen_exhibits=frozenset(documents) or None,
        frozen_accessions=frozenset(accessions) or None,
    ).edgar[0]

    assert listed.corpus_relation == shown
