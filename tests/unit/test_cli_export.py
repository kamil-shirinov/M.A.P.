"""`map export` — the readable state as flat JSON.

Three properties carry the weight, and none of them is about serialisation:

the shape refuses pooling as firmly as `Journal` does; every absence is a stated
fact in the manifest rather than a missing file; and a held filing nothing ran is
exported with an empty run list, because a page showing 701 of 709 would misstate
the record it is drawing.
"""

from __future__ import annotations

import inspect
import json
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner, Result

from mapf.cli.app import EXIT_DATA, app
from mapf.cli.commands.export import UI_EXPORT, _funnel, export
from tests.unit.test_cli import _config
from tests.unit.test_cli_corpus import _frozen
from tests.unit.test_journal import VINTAGE, _write_run

runner = CliRunner()


def _symbols(tmp_path: Path) -> None:
    """A real index at the configured path, built the way `map symbols sync` builds
    one — through the adapter, so the schema and the vintage row cannot drift from
    what the export reads back."""
    import httpx

    from mapf.data.symbols import Throttle, sync

    fixture = Path(__file__).parents[1] / "fixtures" / "sec" / "company_tickers_exchange.json"
    sync(
        tmp_path / "symbols.sqlite",
        url="https://example.test/tickers.json",
        user_agent="Test test@example.com",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=fixture.read_bytes())
            )
        ),
        throttle=Throttle(1000.0, sleep=lambda _: None),
        today=lambda: date(2026, 8, 11),
    )


def _ledger(tmp_path: Path, run_id: str, *, filing: str = "2026-02-01") -> Path:
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        json.dumps(
            {
                "ticker": "AAPL",
                "band": "clean",
                "filing_date": filing,
                "status": "complete",
                "run_id": run_id,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _ready(tmp_path: Path) -> None:
    """The inputs a successful export needs. No price fake: `build_price_snapshot`
    reads the configured cache directory, so a test that wants a series lays down
    real parquet and one that does not gets a named absence."""
    _symbols(tmp_path)
    _filers(tmp_path)


def _filers(tmp_path: Path) -> Path:
    """A two-row pre-screen: one filer that publishes Item 2.02 and one that does
    not. The second is the whole point — 45.9% of real filers answer `false`."""
    path = tmp_path / "item_202.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {
                    "cik": 320193,
                    "tickers": ["AAPL"],
                    "fetched_on": "2026-09-09",
                    "block": "recent",
                    "status": "ok",
                    "item_202_in_recent": True,
                    "count": 4,
                    "most_recent": "2026-07-30",
                },
                {
                    "cik": 2230,
                    "tickers": ["ADX"],
                    "fetched_on": "2026-09-09",
                    "block": "recent",
                    "status": "ok",
                    "item_202_in_recent": False,
                    "count": 0,
                    "most_recent": None,
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _export(tmp_path: Path, *args: str, out: Path | None = None) -> Result:
    # The ledger is isolated like every other path. Left to its default it read
    # the checkout's own `var/corpus/ledger.jsonl`, which is gitignored, so two tests
    # passed here and failed in a clean clone (Findings #67).
    ledger = () if "--ledger-path" in args else ("--ledger-path", str(tmp_path / "no-ledger.jsonl"))
    return runner.invoke(
        app,
        [
            "export",
            *ledger,
            "--out",
            str(out or tmp_path / "export"),
            "--frozen",
            str(_frozen(tmp_path)),
            "--runs-dir",
            str(tmp_path / "runs"),
            "--scores-dir",
            str(tmp_path / "scores"),
            "--filers-path",
            str(tmp_path / "item_202.jsonl"),
            "--snapshot",
            VINTAGE.isoformat(),
            *args,
            "--config",
            str(_config(tmp_path)),
        ],
    )


def _read(tmp_path: Path, name: str) -> Any:
    """`Any`, not `object`: the export holds dicts and lists at the top level and
    every caller indexes the shape it is asserting about."""
    return json.loads((tmp_path / "export" / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The shape refuses pooling
# ---------------------------------------------------------------------------
def test_runs_are_written_per_population_with_no_combined_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same separation `Journal` enforces in memory, carried across the wire.
    A consumer wanting everything must fetch four files and concatenate on purpose."""
    _ready(tmp_path)
    runs = tmp_path / "runs"
    _write_run(runs, source="corpus")
    _write_run(runs, source="edgar", freeze_version=None)

    result = _export(tmp_path, "--ledger-path", str(tmp_path / "absent.jsonl"), "--allow-partial")

    assert result.exit_code == 0, result.output
    by_source = tmp_path / "export" / "runs" / "by_source"
    assert {p.name for p in by_source.iterdir()} == {
        "corpus.json",
        "edgar.json",
        "news.json",
        "unknown.json",
    }
    assert not (tmp_path / "export" / "runs.json").exists()
    assert not (tmp_path / "export" / "runs" / "all.json").exists()


def test_the_manifest_counts_each_population_as_written_and_never_a_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A front door wants "N runs" without fetching 649 KB of records. The manifest
    gives it one count per file, taken from the rows written into that file, and no
    total: the sum is the consumer's to take, in code where the pooling is visible.
    A run the journal cannot read is in no file, so it is in no count."""
    _ready(tmp_path)
    runs = tmp_path / "runs"
    _write_run(runs, source="corpus")
    _write_run(runs, source="corpus")
    _write_run(runs, source="edgar", freeze_version=None)
    _write_run(runs, source=None, freeze_version=None)
    _write_run(runs, source="corpus", manifest=False)

    result = _export(tmp_path, "--ledger-path", str(tmp_path / "absent.jsonl"), "--allow-partial")

    assert result.exit_code == 0, result.output
    rows = _read(tmp_path, "manifest.json")["runs"]
    assert rows == {"rows": {"corpus": 2, "edgar": 1, "news": 0, "unknown": 1}}
    for source, count in rows["rows"].items():
        assert len(_read(tmp_path, f"runs/by_source/{source}.json")) == count


def test_a_run_record_is_the_same_object_map_runs_emits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One serialiser, shared. Two would drift, and the export's whole claim is
    that it says nothing the library does not already say."""
    _ready(tmp_path)
    runs = tmp_path / "runs"
    run_id = _write_run(runs, source="corpus")

    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    exported = _read(tmp_path, "runs/by_source/corpus.json")
    assert isinstance(exported, list)
    assert set(exported[0]) == {
        "anchor_date",
        "anchor_spot",
        # Whether that spot was a settled close or a live quote (Findings #64).
        "price_kind",
        "arm",
        "corpus_relation",
        "document_is_frozen_exhibit",
        "document_source",
        "freeze_version",
        "horizon_days",
        "ledger_item",
        "anchor_drift",
        "outcome",
        "outcome_status",
        "run_id",
        "scenarios",
        "ticker",
        # Recorded at run time; the journal cannot resolve a name outside the 120.
        "company_name",
    }


# ---------------------------------------------------------------------------
# A held filing with no run
# ---------------------------------------------------------------------------
def test_a_filing_nothing_ran_is_exported_with_an_empty_run_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exhibit fact and the run fact are separate. Omitting the filing would
    make the page show fewer filings than the corpus holds."""
    _ready(tmp_path)
    runs = tmp_path / "runs"
    run_id = _write_run(runs, source="corpus")

    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    companies = _read(tmp_path, "corpus.json")
    filings = [f for c in companies for f in c["filings"]]
    assert len(filings) == 3
    assert sum(1 for f in filings if f["runs"]) == 1
    assert sum(1 for f in filings if not f["runs"]) == 2
    # Still present, with band, accession and split intact.
    empty = next(f for f in filings if not f["runs"])
    assert empty["accession"] and empty["band"] and empty["split"]


# ---------------------------------------------------------------------------
# Absences are stated, never missing files
# ---------------------------------------------------------------------------
def test_the_manifest_says_why_there_is_no_holdout_scoring_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A development record is exported and a holdout one is not. A reader must
    learn the reason here rather than infer it from a gap."""
    _ready(tmp_path)
    _write_run(tmp_path / "runs")

    _export(tmp_path, "--ledger-path", str(tmp_path / "absent.jsonl"), "--allow-partial")

    absent = _read(tmp_path, "manifest.json")["scores"]["absent"]
    assert len(absent) == 1
    assert absent[0]["split"] == "holdout"
    assert absent[0]["exported"] is False
    assert "scored once" in absent[0]["reason"]
    assert "cannot be recovered" in absent[0]["reason"]
    assert "holdout_spend.jsonl" in absent[0]["survives_in"]


def test_a_missing_ledger_stops_the_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without it every corpus_relation reads `unchecked` and the per-company run
    lists are empty — a front end would draw a corpus nothing had run."""
    _ready(tmp_path)
    _write_run(tmp_path / "runs")

    result = _export(tmp_path, "--ledger-path", str(tmp_path / "absent.jsonl"))

    assert result.exit_code == EXIT_DATA
    assert "corpus ledger is missing" in result.output


def test_allow_partial_records_the_absence_rather_than_hiding_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready(tmp_path)
    _write_run(tmp_path / "runs")

    result = _export(tmp_path, "--ledger-path", str(tmp_path / "absent.jsonl"), "--allow-partial")

    assert result.exit_code == 0, result.output
    absent = _read(tmp_path, "manifest.json")["absent"]
    # Both gaps, each with its consequence named. `absent` is about inputs that
    # could not be read; `scores.absent` is about a split that cannot exist.
    by_what = {gap["what"]: gap["reason"] for gap in absent}
    # Every gap, each with its consequence named. `absent` is about inputs that
    # could not be read; `scores.absent` is about a split that cannot exist.
    assert set(by_what) == {"ledger", "prices", "scores"}
    assert "unchecked" in by_what["ledger"]
    assert "no scoring pass" in by_what["scores"]
    assert "no window in the" in by_what["prices"]
    assert "absent     ledger" in result.output


def test_a_missing_symbol_index_stops_the_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never an empty index: a front end reading one would show "no results" for
    every search instead of "this export has no symbols"."""
    _write_run(tmp_path / "runs")
    run_id = _write_run(tmp_path / "runs")

    result = _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    assert result.exit_code == EXIT_DATA
    assert "symbol index is missing" in result.output
    assert "map symbols sync" in result.output


def test_a_missing_frozen_corpus_stops_even_with_allow_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It is the pre-registration. There is no partial export without it."""

    result = runner.invoke(
        app,
        [
            "export",
            "--out",
            str(tmp_path / "export"),
            "--frozen",
            str(tmp_path / "absent.json"),
            "--allow-partial",
            "--config",
            str(_config(tmp_path)),
        ],
    )

    assert result.exit_code == EXIT_DATA
    assert "frozen corpus is missing" in result.output


def test_a_scoring_record_is_content_addressed_in_the_manifest(tmp_path: Path) -> None:
    """Band, split, vintage and code digest — the same identity as the filename, so
    a reader can tell from the manifest alone whether the pass matches the code
    state the rest of the export came from."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")
    scores = tmp_path / "scores"
    scores.mkdir()
    (scores / "clean.dev.2026-09-05.abc123abc123.json").write_text(
        json.dumps(
            {
                "band": "clean",
                "split": "dev",
                "vintage": "2026-09-05",
                "forecast_digest": "abc123abc123",
                "freeze_version": "2.6.0",
                "n": 175,
                "items": [],
            }
        ),
        encoding="utf-8",
    )

    result = _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    assert result.exit_code == 0, result.output
    manifest = _read(tmp_path, "manifest.json")
    assert manifest["scores"]["records"] == [
        {
            "file": "scores/clean.dev.2026-09-05.abc123abc123.json",
            "band": "clean",
            "split": "dev",
            "vintage": "2026-09-05",
            "forecast_digest": "abc123abc123",
            "freeze_version": "2.6.0",
            "n": 175,
        }
    ]
    # And the record itself travels, not only its identity.
    assert _read(tmp_path, "scores/clean.dev.2026-09-05.abc123abc123.json")["n"] == 175


def test_two_passes_under_different_code_are_both_carried_and_distinguishable(
    tmp_path: Path,
) -> None:
    """Write-once per identity means a re-run after a code change lands beside its
    predecessor. The export carries both, and the digest is what tells them apart."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")
    scores = tmp_path / "scores"
    scores.mkdir()
    for digest in ("aaaaaaaaaaaa", "bbbbbbbbbbbb"):
        (scores / f"clean.dev.2026-09-05.{digest}.json").write_text(
            json.dumps(
                {
                    "band": "clean",
                    "split": "dev",
                    "vintage": "2026-09-05",
                    "forecast_digest": digest,
                    "freeze_version": "2.6.0",
                    "n": 175,
                    "items": [],
                }
            ),
            encoding="utf-8",
        )

    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    records = _read(tmp_path, "manifest.json")["scores"]["records"]
    assert [r["forecast_digest"] for r in records] == ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]
    assert len({r["file"] for r in records}) == 2


def test_the_manifest_carries_each_sources_own_stamp_not_one_invented_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single export-wide vintage would flatten several moments into one date and
    assert a uniformity that does not exist."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")

    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    manifest = _read(tmp_path, "manifest.json")
    assert manifest["freeze"]["version"] == "2.0.0"
    assert manifest["freeze"]["digest"]
    assert manifest["prices"]["snapshot"] == VINTAGE.isoformat()
    assert manifest["ledger"]["items_settled"] == 1
    assert manifest["export_version"] == "1.4.0"
    # The pre-screen's own stamps, as the set they are: every row carries its
    # `fetched_on` and a resumed walk spans days.
    assert manifest["filers"] == {"rows": 2, "distinct": 2, "vintages": ["2026-09-09"]}
    # UTC, matching what the export stamps. See test_cli_runs for why.
    assert manifest["exported_at"] == datetime.now(UTC).date().isoformat()


def test_the_universe_is_eager_and_the_full_index_is_a_separate_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """120 companies have something to show; 10,398 tickers are only needed once
    someone types. Splitting them is what keeps first paint small."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")

    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    universe = _read(tmp_path, "universe.json")
    assert [u["ticker"] for u in universe] == ["AAPL"]
    assert set(universe[0]) == {"ticker", "name", "split"}
    assert (tmp_path / "export" / "symbols.json").is_file()


def test_the_longest_stored_window_becomes_the_company_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Against a REAL snapshot over a real parquet store, because this is the path
    production takes: the stored windows end near each filing's anchor and almost
    never span the snapshot's own date, so a lookup keyed on that date would return
    nothing for nearly every company."""
    from tests.unit.test_data_prices import _store

    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")
    prices = tmp_path / "prices"
    _store(prices, "AAPL", VINTAGE.isoformat(), date(2026, 1, 5), 8)
    _store(prices, "AAPL", VINTAGE.isoformat(), date(2026, 1, 5), 30)

    result = _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    assert result.exit_code == 0, result.output
    series = _read(tmp_path, "prices/AAPL.json")
    assert len(series["bars"]) == 30
    assert series["snapshot"] == VINTAGE.isoformat()


def test_a_vintage_holding_nothing_for_a_company_writes_no_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real snapshot, empty store. Nothing is drawn where nothing is held."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")

    result = _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    assert result.exit_code == 0, result.output
    assert not (tmp_path / "export" / "prices").exists()
    absent = _read(tmp_path, "manifest.json")["absent"]
    assert any(gap["what"] == "prices" for gap in absent)


def test_a_stray_filename_in_the_vintage_does_not_stop_the_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_data_prices import _store

    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")
    prices = tmp_path / "prices"
    _store(prices, "AAPL", VINTAGE.isoformat(), date(2026, 1, 5), 12)
    (prices / "AAPL" / "split_adjusted" / VINTAGE.isoformat() / "notes.parquet").write_bytes(b"x")

    result = _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    assert result.exit_code == 0, result.output
    assert len(_read(tmp_path, "prices/AAPL.json")["bars"]) == 12


def test_a_missing_symbol_index_can_be_exported_around_when_declared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only with --allow-partial, and the consequence is named: search cannot
    resolve anything outside the corpus."""
    run_id = _write_run(tmp_path / "runs")

    result = _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)), "--allow-partial")

    assert result.exit_code == 0, result.output
    assert not (tmp_path / "export" / "symbols.json").exists()
    by_what = {gap["what"]: gap["reason"] for gap in _read(tmp_path, "manifest.json")["absent"]}
    assert "outside the corpus" in by_what["symbols"]
    # The universe still lists the company; only its display name is unknown.
    assert _read(tmp_path, "universe.json")[0]["name"] is None


def test_a_config_failure_is_a_sentence_not_a_traceback(tmp_path: Path) -> None:
    from mapf.cli.app import EXIT_CONFIG

    # A named config file that does not exist. The SEC placeholder no longer
    # serves here: this command contacts nobody, and refusing it on a
    # credential it never uses is the coupling this test now guards against.
    config = tmp_path / "absent.toml"
    result = runner.invoke(
        app, ["export", "--out", str(tmp_path / "export"), "--config", str(config)]
    )

    assert result.exit_code == EXIT_CONFIG
    assert "no configuration file found" in result.output


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------
def _check(tmp_path: Path, *args: str) -> Result:
    return runner.invoke(
        app,
        [
            "export",
            "--check",
            "--out",
            str(tmp_path / "export"),
            "--frozen",
            str(_frozen(tmp_path)),
            "--ledger-path",
            str(tmp_path / "ledger.jsonl"),
            # Isolated like every other path the helper passes. It was not, and
            # nothing noticed because nothing read it until the run counts joined
            # the identities `--check` compares (ADR 0036 §5) — at which point the
            # check was reading the repository's own 779 runs.
            "--runs-dir",
            str(tmp_path / "runs"),
            "--filers-path",
            str(tmp_path / "item_202.jsonl"),
            "--snapshot",
            VINTAGE.isoformat(),
            *args,
            "--config",
            str(_config(tmp_path)),
        ],
    )


def test_check_reports_a_current_export_as_current(tmp_path: Path) -> None:
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")
    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    result = _check(tmp_path)

    assert result.exit_code == 0, result.output
    assert "nothing has moved; the export is current" in result.output


def test_check_names_the_input_that_moved(tmp_path: Path) -> None:
    """A date alone does not make staleness visible — a reader sees when it was
    written, not whether it is still true. The identity of each input does."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")
    ledger = _ledger(tmp_path, run_id)
    _export(tmp_path, "--ledger-path", str(ledger))

    # A second item lands in the ledger after the export was written.
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "ticker": "AAPL",
                    "band": "clean",
                    "filing_date": "2026-05-01",
                    "status": "complete",
                    "run_id": _write_run(tmp_path / "runs"),
                }
            )
            + "\n"
        )

    result = _check(tmp_path, "--ledger-path", str(ledger))

    assert "moved      ledger.items_settled: 1 -> 2" in result.output
    # Two, and they are different facts: the ledger settled another item, and a run
    # directory appeared. Reported separately, which is the whole point of carrying
    # a count per source rather than a total (ADR 0036 §5).
    assert "moved      runs.corpus: 1 -> 2" in result.output
    assert "2 of 11 inputs have moved" in result.output


def test_check_writes_nothing(tmp_path: Path) -> None:
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")
    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))
    before = {p.name: p.stat().st_mtime_ns for p in (tmp_path / "export").rglob("*")}

    _check(tmp_path)

    after = {p.name: p.stat().st_mtime_ns for p in (tmp_path / "export").rglob("*")}
    assert before == after


def test_check_repeats_the_absences_the_export_recorded(tmp_path: Path) -> None:
    """A reader checking freshness also learns what was never in it. Silence here
    would make a stated absence look like a gap after all."""
    _ready(tmp_path)
    _write_run(tmp_path / "runs")
    _export(tmp_path, "--ledger-path", str(tmp_path / "absent.jsonl"), "--allow-partial")

    result = _check(tmp_path, "--ledger-path", str(tmp_path / "absent.jsonl"))

    assert "absent     ledger:" in result.output
    assert "absent     scores/holdout:" in result.output
    assert "cannot be recovered" in result.output


def test_check_on_a_directory_with_no_export_says_so(tmp_path: Path) -> None:
    _ready(tmp_path)

    result = _check(tmp_path)

    assert result.exit_code == EXIT_DATA
    assert "no export at" in result.output
    assert "map export --out" in result.output


def test_a_format_change_is_reported_before_anything_else(tmp_path: Path) -> None:
    """A front end is entitled to refuse a shape it does not know, and comparing
    identities across two formats compares fields that may not mean the same thing."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")
    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))
    manifest = tmp_path / "export" / "manifest.json"
    body = json.loads(manifest.read_text(encoding="utf-8"))
    body["export_version"] = "0.9.0"
    manifest.write_text(json.dumps(body), encoding="utf-8")

    result = _check(tmp_path)

    assert "format     export is 0.9.0" in result.output
    assert "re-export before comparing" in result.output


def test_check_survives_an_input_that_has_since_disappeared(tmp_path: Path) -> None:
    """The symbol index is untracked, so a fresh clone of a machine that had one is
    exactly this case. It reads as moved, not as a crash."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")
    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))
    (tmp_path / "symbols.sqlite").unlink()

    result = _check(tmp_path)

    assert result.exit_code == 0, result.output
    assert "moved      symbols.synced_on: 2026-08-11 -> None" in result.output


# ---------------------------------------------------------------------------
# The pre-screen
# ---------------------------------------------------------------------------
def test_the_pre_screen_travels_as_written(tmp_path: Path) -> None:
    """Search must answer a question the corpus cannot: of the tickers someone can
    type, which belong to a filer that publishes earnings 8-Ks at all. Without it
    every ticker outside the corpus looks equally viable."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")

    result = _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    assert result.exit_code == 0, result.output
    filers = _read(tmp_path, "filers.json")
    assert [f["item_202_in_recent"] for f in filers] == [True, False]
    # Rows as written, including the ones that answer no — 45.9% of real filers do.
    assert filers[1]["tickers"] == ["ADX"]
    assert filers[0]["fetched_on"] == "2026-09-09"


def test_a_missing_pre_screen_stops_the_export(tmp_path: Path) -> None:
    _symbols(tmp_path)
    run_id = _write_run(tmp_path / "runs")

    result = _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    assert result.exit_code == EXIT_DATA
    assert "Item 2.02 pre-screen is missing" in result.output
    assert "edgar_prescreen.py" in result.output


def test_a_declared_missing_pre_screen_names_what_search_loses(tmp_path: Path) -> None:
    _symbols(tmp_path)
    run_id = _write_run(tmp_path / "runs")

    result = _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)), "--allow-partial")

    assert result.exit_code == 0, result.output
    by_what = {gap["what"]: gap["reason"] for gap in _read(tmp_path, "manifest.json")["absent"]}
    assert "publishes Item 2.02" in by_what["filers"]
    assert not (tmp_path / "export" / "filers.json").exists()


def test_the_holdout_spend_record_travels_and_its_absence_entry_points_at_it(
    tmp_path: Path,
) -> None:
    """All that survives of the holdout is its terms. The per-item scores were
    printed once and never written, so the spend record is the only holdout
    artifact there is — and an interface can state the terms rather than only the
    absence."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")
    spend = tmp_path / "holdout_spend.jsonl"
    spend.write_text(
        json.dumps(
            {
                "band": "clean",
                "calibration": {"a": -0.0757, "b": 1.3305, "form": "z -> (z - a) / b"},
                "items": 173,
                "scored_on": "2026-09-05",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)), "--spend-path", str(spend))

    body = _read(tmp_path, "scores/holdout_spend.json")
    assert isinstance(body, list), "append-only: a second spend would be a second line"
    assert body[0]["calibration"]["b"] == 1.3305
    assert "map_crps" not in json.dumps(body), "the spend record carries no scores"
    absent = _read(tmp_path, "manifest.json")["scores"]["absent"][0]
    assert absent["exported_as"] == "scores/holdout_spend.json"
    assert absent["spends"] == 1
    assert absent["exported"] is False, "the SCORES are still absent; only the terms travel"


def test_a_missing_spend_record_is_an_absence_rather_than_a_silent_gap(tmp_path: Path) -> None:
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")

    result = _export(
        tmp_path,
        "--ledger-path",
        str(_ledger(tmp_path, run_id)),
        "--spend-path",
        str(tmp_path / "nowhere.jsonl"),
    )

    assert result.exit_code == 0, result.output
    manifest = _read(tmp_path, "manifest.json")
    assert manifest["scores"]["absent"][0]["exported_as"] is None
    assert any(gap["what"] == "holdout_spend" for gap in manifest["absent"])


def test_the_ledger_figure_cannot_be_read_as_a_run_count(tmp_path: Path) -> None:
    """It is every item the ledger will not attempt again — 701 complete plus 8
    terminal failures in the real corpus, which is exactly why 8 held filings carry
    an empty run list. A key called `resolved` invited the wrong reading."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")

    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    ledger = _read(tmp_path, "manifest.json")["ledger"]
    assert set(ledger) == {"items_settled"}
    assert "resolved" not in ledger
    assert "runs" not in json.dumps(ledger)


def test_a_long_absence_keeps_its_list_out_of_the_sentence(tmp_path: Path) -> None:
    """On a fresh clone every company is unpriced, and naming all 120 inline put a
    wall of tickers in the middle of the output — printed again by `--check`. The
    list is worth keeping and worth not reading."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")

    result = _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    gap = next(g for g in _read(tmp_path, "manifest.json")["absent"] if g["what"] == "prices")
    assert gap["items"] == ["AAPL"]
    assert "AAPL" not in gap["reason"]
    assert gap["reason"].endswith("snapshot")
    assert "no window in the" in result.output


def test_more_names_than_fit_are_counted_rather_than_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mapf.cli.commands import export as export_module

    printed: list[str] = []
    monkeypatch.setattr(typer, "secho", lambda text, **_: printed.append(str(text)))
    export_module._print_absence(
        {"what": "prices", "reason": "9 companies have no window", "items": list("ABCDEFGHI")}
    )

    assert printed[1].strip() == "A, B, C, D, E, F, and 3 more"


def test_an_absence_with_no_list_prints_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    from mapf.cli.commands import export as export_module

    printed: list[str] = []
    monkeypatch.setattr(typer, "secho", lambda text, **_: printed.append(str(text)))
    export_module._print_absence({"what": "scores", "reason": "no scoring pass has been recorded"})

    assert len(printed) == 1


def test_the_chart_takes_the_most_recent_window_not_the_longest(tmp_path: Path) -> None:
    """Selecting on span alone put 92 of 120 charts a median 273 days behind data
    the same vintage held: every window is about 764 days, so span was effectively a
    tie and the winner was whichever the filesystem yielded first."""
    from tests.unit.test_data_prices import _store

    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")
    prices = tmp_path / "prices"
    _store(prices, "AAPL", VINTAGE.isoformat(), date(2025, 1, 6), 40)  # older, longer
    _store(prices, "AAPL", VINTAGE.isoformat(), date(2026, 1, 5), 30)  # newer, shorter

    result = _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    assert result.exit_code == 0, result.output
    bars = _read(tmp_path, "prices/AAPL.json")["bars"]
    assert bars[-1][0] == "2026-02-03"
    assert len(bars) == 30


def test_span_still_breaks_a_tie_on_the_end_date(tmp_path: Path) -> None:
    """Two windows ending the same day: take the one reaching further back."""
    from tests.unit.test_data_prices import _store

    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")
    prices = tmp_path / "prices"
    _store(prices, "AAPL", VINTAGE.isoformat(), date(2026, 1, 25), 10)
    _store(prices, "AAPL", VINTAGE.isoformat(), date(2026, 1, 5), 30)

    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    assert len(_read(tmp_path, "prices/AAPL.json")["bars"]) == 30


def test_the_default_output_is_where_the_front_end_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One channel between the Python and the JavaScript, and one path.

    `ui/assets/export` is the only place a page can read from, so it is the default
    rather than the usual argument. A required `--out` made it possible — and, for
    a while, routine — to write a valid export that no screen could see.
    """
    assert Path("ui/assets/export") == UI_EXPORT

    assert inspect.signature(export).parameters["out"].default.default == UI_EXPORT

    # And behaviourally, from a directory with no export in it: the command that
    # names the path it looked in must name that one when nobody passed --out.
    config = _config(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["export", "--check", "--config", str(config)])
    assert result.exit_code == EXIT_DATA
    assert str(UI_EXPORT) in result.output

    # And the directory it names is ignored, not committed: 5 MB of derived JSON
    # that this command rebuilds. Asserted against the real repository, because the
    # default is only useful if writing to it does not dirty the tree.
    root = Path(__file__).resolve().parents[2]
    ignored = subprocess.run(  # noqa: S603, S607
        ["git", "check-ignore", "ui/assets/export/manifest.json"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ignored.returncode == 0, "ui/assets/export/ must be gitignored"


def test_no_prices_omits_the_series_and_the_exporter_states_the_absence(tmp_path: Path) -> None:
    """The bars are the largest thing in the export and the only third-party
    series published in bulk. `--no-prices` leaves them out.

    THE MANIFEST STATES IT, not a build script. Deleting `prices/` after the fact
    would leave a manifest claiming a snapshot it did not ship, and the absence
    would be written by whatever removed the files rather than by the thing that
    knows what it did.
    """
    _ready(tmp_path)

    result = _export(tmp_path, "--no-prices", "--allow-partial")

    assert result.exit_code == 0, result.output
    assert not (tmp_path / "export" / "prices").exists(), "no series were written"

    manifest = _read(tmp_path, "manifest.json")
    absence = next(a for a in manifest["absent"] if a["what"] == "prices")
    assert "were not exported" in absence["reason"]
    assert manifest["prices"]["companies"] == 0

    # And nothing else moves. Every close the journal and the scores carry comes
    # from the run artifacts, not from these files.
    assert (tmp_path / "export" / "corpus.json").exists()
    assert (tmp_path / "export" / "universe.json").exists()
    assert (tmp_path / "export" / "runs" / "by_source" / "unknown.json").exists()


def test_prices_are_exported_by_default(tmp_path: Path) -> None:
    """The flag is opt-in, and the two prices absences say different things.

    This fixture's companies have no window in the snapshot, so a default export
    already records a prices absence — for a different reason. The wording is how
    a reader tells "the snapshot held nothing for these" from "these were
    deliberately left out", and the two must not collapse into one message.
    """
    _ready(tmp_path)

    result = _export(tmp_path, "--allow-partial")

    assert result.exit_code == 0, result.output
    manifest = _read(tmp_path, "manifest.json")
    absence = next(a for a in manifest["absent"] if a["what"] == "prices")
    assert "have no window" in absence["reason"]
    assert "were not exported" not in absence["reason"]


# --- the funnel, counted at export over one base -------------------------------


def test_the_funnel_is_counted_and_its_parts_sum_to_the_base(tmp_path: Path) -> None:
    """Counted here rather than in the browser, because counting it there means a
    pass over filers.json at 1.2 MB on every page load.

    The sum is the property worth asserting: a funnel whose parts do not add up to
    its base is a screen reporting a drop that did not happen."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")

    result = _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    assert result.exit_code == 0, result.output
    funnel = _read(tmp_path, "manifest.json")["funnel"]
    parts = ("earnings_filer", "no_earnings_filings", "unscreened")
    assert sum(funnel[k] for k in parts) == funnel["tickers"]
    assert funnel["frozen"] + funnel["readable_unread"] == funnel["earnings_filer"]


def test_the_frozen_count_is_counted_not_subtracted(tmp_path: Path) -> None:
    """`readable_unread` is the tickers an earnings filer holds that the freeze did
    not take, counted as such. Subtracting 120 from the readable count would still
    balance if a corpus ticker were missing from the index, and the screen would
    then report a drop that never happened."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")

    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    funnel = _read(tmp_path, "manifest.json")["funnel"]
    universe = _read(tmp_path, "universe.json")
    symbols = {r["ticker"] for r in _read(tmp_path, "symbols.json")}
    # Only corpus tickers the index actually carries can be counted as frozen.
    assert funnel["frozen"] == sum(1 for c in universe if c["ticker"] in symbols)


def test_a_filer_whose_screen_failed_is_not_counted_as_having_no_filings(
    tmp_path: Path,
) -> None:
    """`status != ok` means the flag was never read, which is a different fact from
    reading it and finding nothing. Conflating them would move a ticker into the
    "nothing to read" stage on the strength of a failed HTTP request."""
    _symbols(tmp_path)
    path = _filers(tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    rows[1] = {**rows[1], "status": "request_failed", "item_202_in_recent": None, "count": None}
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    run_id = _write_run(tmp_path / "runs")

    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    funnel = _read(tmp_path, "manifest.json")["funnel"]
    assert funnel["unscreened"] >= 1
    assert (
        sum(funnel[k] for k in ("earnings_filer", "no_earnings_filings", "unscreened"))
        == funnel["tickers"]
    )


def test_a_retried_filer_counts_once_and_the_retry_wins(tmp_path: Path) -> None:
    """The real export has 8,001 rows over 7,998 filers: three CIKs carry a failed
    request followed by the retry that succeeded. The LAST row for a CIK is the
    pre-screen's final answer, and the manifest states both numbers so a page
    printing one base knows which it has."""
    _symbols(tmp_path)
    path = _filers(tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    failed = {**rows[0], "status": "request_failed", "item_202_in_recent": None, "count": None}
    # The failure first, the success after it — the order the walk writes them in.
    path.write_text("\n".join(json.dumps(r) for r in [failed, *rows]) + "\n")
    run_id = _write_run(tmp_path / "runs")

    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    manifest = _read(tmp_path, "manifest.json")
    assert manifest["filers"]["rows"] == manifest["filers"]["distinct"] + 1
    # The retry's answer stands, so AAPL is still counted on an earnings filer.
    assert manifest["funnel"]["earnings_filer"] >= 1
    # And the failed attempt moved nothing: the only unscreened tickers are the
    # ones whose CIK the pre-screen never covered at all.
    screened = {r["cik"] for r in _read(tmp_path, "filers.json")}
    symbols = _read(tmp_path, "symbols.json")
    assert manifest["funnel"]["unscreened"] == sum(1 for r in symbols if r["cik"] not in screened)


def test_the_funnel_partitions_a_hand_built_index() -> None:
    """`_funnel` directly, because the CLI fixtures cannot reach every arm: the
    six-symbol test index has no ticker that sits on an earnings filer outside the
    corpus, which is the largest stage of the real funnel at 5,189 of 10,398."""
    symbols = [
        {"ticker": "AAPL", "cik": 1},  # earnings filer, frozen
        {"ticker": "MSFT", "cik": 1},  # same filer, NOT frozen
        {"ticker": "NVDA", "cik": 2},  # earnings filer, not frozen
        {"ticker": "ADX", "cik": 3},  # filer with no Item 2.02
        {"ticker": "BXRLY", "cik": 4},  # screen failed
        {"ticker": "ZZQ", "cik": 9},  # no filer row at all
    ]
    filers = [
        {"cik": 1, "status": "ok", "item_202_in_recent": True},
        {"cik": 2, "status": "ok", "item_202_in_recent": True},
        {"cik": 3, "status": "ok", "item_202_in_recent": False},
        {"cik": 4, "status": "request_failed", "item_202_in_recent": None},
    ]

    funnel = _funnel(symbols, filers, [{"ticker": "AAPL"}])

    assert funnel == {
        "tickers": 6,
        "earnings_filer": 3,
        "frozen": 1,
        "readable_unread": 2,
        "no_earnings_filings": 1,
        "unscreened": 2,
    }
    # One filer, three tickers: the reason the screen has one base rather than two.
    assert funnel["earnings_filer"] > len({f["cik"] for f in filers if f["item_202_in_recent"]})


def test_the_last_row_for_a_filer_is_the_one_the_funnel_reads() -> None:
    """A failed attempt followed by its retry, which is what the three repeated
    CIKs in the real export are. The retry is the pre-screen's final answer."""
    symbols = [{"ticker": "BXRLY", "cik": 4}]
    failed = {"cik": 4, "status": "request_failed", "item_202_in_recent": None}
    retried = {"cik": 4, "status": "ok", "item_202_in_recent": False}

    assert _funnel(symbols, [failed, retried], [])["no_earnings_filings"] == 1
    assert _funnel(symbols, [failed, retried], [])["unscreened"] == 0
    # And with no retry it stays unscreened rather than being read as a negative.
    assert _funnel(symbols, [failed], [])["unscreened"] == 1


# --- ADR 0036 §5: a live run moves the EDGAR count and nothing else ------------


def _identities(tmp_path: Path) -> dict[str, tuple[object, object]]:
    """What `--check` compares: the export's stamps against this checkout's."""
    from mapf.cli.commands.export import _exported_identity, _live_identity
    from mapf.settings.loader import load

    manifest = _read(tmp_path, "manifest.json")
    settings = load([_config(tmp_path)])
    live = _live_identity(
        settings,
        frozen=tmp_path / "frozen.json",
        ledger_path=tmp_path / "ledger.jsonl",
        vintage=VINTAGE,
        runs_dir=tmp_path / "runs",
    )
    was = _exported_identity(manifest)
    return {key: (was[key], live[key]) for key in live}


def test_the_check_reports_run_counts_by_source_not_a_total(tmp_path: Path) -> None:
    """A total would hide WHICH source moved, which is the only thing worth knowing
    when a run appears under an export."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")

    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    compared = _identities(tmp_path)
    for source in ("corpus", "edgar", "news", "unknown"):
        assert f"runs.{source}" in compared, source
    assert "runs.total" not in compared


def test_a_live_run_moves_the_edgar_count_and_nothing_else(tmp_path: Path) -> None:
    """ADR 0036 §5. A live run writes one directory whose `document_source` is
    `edgar`. The freeze, the code, the ledger, the symbol vintage and the price
    snapshot are untouched — and if one of them ever moves, something has written
    into the corpus and this is the check that says so before an export carries it."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")
    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))
    before = _identities(tmp_path)
    assert not [k for k, (was, now) in before.items() if was != now], before

    # The live run, exactly as `map run --from-edgar` records one.
    _write_run(tmp_path / "runs", ticker="MSFT", source="edgar")

    after = _identities(tmp_path)
    moved = {k for k, (was, now) in after.items() if was != now}
    assert moved == {"runs.edgar"}, moved
    assert after["runs.edgar"] == (0, 1)


def test_a_run_written_into_the_corpus_source_is_visible_as_such(tmp_path: Path) -> None:
    """The negative case the previous test exists to catch. A run recorded as a
    corpus item moves a different key, and `--check` names it rather than reporting
    one undifferentiated count."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")
    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    _write_run(tmp_path / "runs", ticker="MSFT", source="corpus")

    moved = {k for k, (was, now) in _identities(tmp_path).items() if was != now}
    assert moved == {"runs.corpus"}


def test_run_counts_are_absent_rather_than_zero_with_no_runs_directory(
    tmp_path: Path,
) -> None:
    """Zero runs and no journal at all are different facts. Reporting `0` for a
    directory that does not exist would say the journal was read and found empty."""
    from mapf.cli.commands.export import _run_counts

    counts = _run_counts(tmp_path / "nowhere")
    assert set(counts) == {"runs.corpus", "runs.edgar", "runs.news", "runs.unknown"}
    assert all(value is None for value in counts.values())


def test_the_replay_is_pinned_by_id_and_absent_when_that_run_is_not_here(
    tmp_path: Path,
) -> None:
    """The hosted copy replays ONE recorded run, named in source. "The newest live
    run" would republish whatever happened locally — a live claim by another route,
    and it would have published the accidental run of Findings #63.

    A fixture export holds no such run, so the manifest names it and the file is
    absent. That is the honest pair: the pin is stated, and what it points at is
    not invented."""
    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs")

    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    manifest = _read(tmp_path, "manifest.json")
    from mapf.cli.commands.export import REPLAY_RUN_ID

    assert manifest["replay"]["run_id"] == REPLAY_RUN_ID
    assert manifest["replay"]["exported_as"] is None
    assert "live/replay.json" not in manifest["files"]


def test_the_replay_is_written_when_the_pinned_run_is_present(tmp_path: Path) -> None:
    from mapf.cli.commands.export import REPLAY_RUN_ID

    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs", ticker="KO", source="edgar")
    # Rename the directory to the pinned id, which is what the exporter looks for.
    (tmp_path / "runs" / run_id).rename(tmp_path / "runs" / REPLAY_RUN_ID)
    import json as _json

    forecast = tmp_path / "runs" / REPLAY_RUN_ID / "forecast.json"
    body = _json.loads(forecast.read_text())
    body["run_id"] = REPLAY_RUN_ID
    forecast.write_text(_json.dumps(body))
    manifest_path = tmp_path / "runs" / REPLAY_RUN_ID / "manifest.json"
    stored = _json.loads(manifest_path.read_text())
    stored["run_id"] = REPLAY_RUN_ID
    manifest_path.write_text(_json.dumps(stored))

    _export(tmp_path, "--ledger-path", str(_ledger(tmp_path, run_id)))

    manifest = _read(tmp_path, "manifest.json")
    assert manifest["replay"]["exported_as"] == "live/replay.json"
    row = _read(tmp_path, "live/replay.json")
    assert row["run_id"] == REPLAY_RUN_ID
    assert row["document_source"] == "edgar"


def test_a_replay_whose_forecast_cannot_be_read_still_exports_the_row(
    tmp_path: Path,
) -> None:
    """A replay without a band is a smaller page, not a broken one. The journal row
    is what makes the page work; the band is what makes it informative.

    Driven through `_write_replay` with a runs directory that does not hold the
    forecast, because the journal and the band read the same file — so the only
    way one succeeds and the other fails is for them to be looking in different
    places, which is exactly what a moved or partially copied `runs/` gives you.
    """
    from datetime import UTC, datetime

    from mapf.cli.commands.export import REPLAY_RUN_ID, _write_replay
    from mapf.eval.journal import read_journal

    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs", ticker="KO", source="edgar")
    (tmp_path / "runs" / run_id).rename(tmp_path / "runs" / REPLAY_RUN_ID)
    for name in ("forecast.json", "manifest.json"):
        path = tmp_path / "runs" / REPLAY_RUN_ID / name
        body = json.loads(path.read_text())
        body["run_id"] = REPLAY_RUN_ID
        path.write_text(json.dumps(body))

    journal = read_journal(tmp_path / "runs", snapshot=None, today=datetime.now(UTC).date())
    sizes: dict[str, int] = {}
    written = _write_replay(tmp_path / "out", journal, sizes, tmp_path / "elsewhere")

    assert written == "live/replay.json"
    row = json.loads((tmp_path / "out" / "live" / "replay.json").read_text())
    assert row["run_id"] == REPLAY_RUN_ID
    assert row["band"] == []
    # The classification survives: the journal decided it from the manifest, so
    # losing the forecast file here costs the band and the instant, not the kind.
    assert row["price_kind"] == "close"
    assert "price_taken_at" not in row


# --- the replay's fan and history (1.4.0) ----------------------------------------


def _pinned(tmp_path: Path) -> Any:
    """A journal holding the pinned run, with its manifest dated like the real one."""
    from datetime import UTC, datetime

    from mapf.cli.commands.export import REPLAY_RUN_ID
    from mapf.eval.journal import read_journal

    _ready(tmp_path)
    run_id = _write_run(tmp_path / "runs", ticker="KO", source="edgar")
    (tmp_path / "runs" / run_id).rename(tmp_path / "runs" / REPLAY_RUN_ID)
    for name in ("forecast.json", "manifest.json"):
        path = tmp_path / "runs" / REPLAY_RUN_ID / name
        body = json.loads(path.read_text())
        body["run_id"] = REPLAY_RUN_ID
        path.write_text(json.dumps(body))
    return read_journal(tmp_path / "runs", snapshot=None, today=datetime.now(UTC).date())


def test_the_replay_carries_a_fan_that_ends_on_its_band(tmp_path: Path) -> None:
    from mapf.cli.commands.export import _write_replay

    journal = _pinned(tmp_path)
    _write_replay(tmp_path / "out", journal, {}, tmp_path / "runs")
    row = json.loads((tmp_path / "out" / "live" / "replay.json").read_text())
    fan = row["fan"]
    assert fan["levels"][0] == 0.05 and len(fan["levels"]) == 19
    at_horizon = dict(zip(fan["levels"], fan["sessions"][-1]["prices"], strict=True))
    for point in row["band"]:
        assert at_horizon[point["level"]] == pytest.approx(point["price"], rel=1e-12)
    assert [c["name"] for c in row["scenario_paths"]] == ["bullish", "base_case", "bearish"]
    # No history reader: the export left prices out, and says so.
    assert row["history"] is None
    assert row["history_why"] == "prices were left out of this export"


def test_the_replay_history_is_read_from_the_runs_own_vintage(tmp_path: Path) -> None:
    """The run's manifest names the day its prices were stored. That vintage — not
    the export's snapshot — is where the last point equals the price the run
    opened from."""
    from mapf.cli.commands.export import REPLAY_RUN_ID, _write_replay

    journal = _pinned(tmp_path)
    manifest = json.loads((tmp_path / "runs" / REPLAY_RUN_ID / "manifest.json").read_text())
    stored_on = date.fromisoformat(manifest["prices"]["fetched_on"])
    anchor = journal.of("edgar")[0].anchor_date
    asked: list[tuple[str, date, date]] = []

    class _Bar:
        def __init__(self, day: date, close: float) -> None:
            self.date = day
            self.close = close

    class _Window:
        bars = [_Bar(anchor - timedelta(days=d), 100.0 + d) for d in range(100, -3, -1)]

    def reader(ticker: str, vintage: date, end: date) -> Any:
        asked.append((ticker, vintage, end))
        return _Window()

    _write_replay(tmp_path / "out", journal, {}, tmp_path / "runs", history_for=reader)
    row = json.loads((tmp_path / "out" / "live" / "replay.json").read_text())
    assert asked == [("KO", stored_on, anchor)]
    assert row["history_vintage"] == stored_on.isoformat()
    assert row["history_why"] is None
    assert len(row["history"]) == 63
    assert row["history"][-1][0] == anchor.isoformat(), "nothing after the anchor"


def test_a_vintage_with_no_window_is_a_stated_absence(tmp_path: Path) -> None:
    from mapf.cli.commands.export import _write_replay

    journal = _pinned(tmp_path)
    _write_replay(tmp_path / "out", journal, {}, tmp_path / "runs", history_for=lambda *_a: None)
    row = json.loads((tmp_path / "out" / "live" / "replay.json").read_text())
    assert row["history"] is None
    assert "price vintage holds no window for KO" in row["history_why"]


def test_the_exporter_reads_the_replay_history_without_fetching(tmp_path: Path) -> None:
    """Through the export command: the reader it builds is a read-only snapshot at
    the run's own vintage, and --no-prices builds none."""
    from mapf.cli.commands.export import REPLAY_RUN_ID

    _pinned(tmp_path)
    ledger = _ledger(tmp_path, REPLAY_RUN_ID)
    _export(tmp_path, "--ledger-path", str(ledger))
    row = _read(tmp_path, "live/replay.json")
    # The fixture's cache holds no window at that vintage: stated, not fetched.
    assert row["history"] is None
    assert "holds no window" in row["history_why"]
    _export(tmp_path, "--ledger-path", str(ledger), "--no-prices")
    row = _read(tmp_path, "live/replay.json")
    assert row["history_why"] == "prices were left out of this export"
