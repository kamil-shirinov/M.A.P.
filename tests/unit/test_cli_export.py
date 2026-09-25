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
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapf.cli.app import EXIT_DATA, app
from mapf.cli.commands.export import UI_EXPORT, export
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


def _export(tmp_path: Path, *args: str, out: Path | None = None) -> object:
    return runner.invoke(
        app,
        [
            "export",
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


def _read(tmp_path: Path, name: str) -> object:
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
    assert manifest["export_version"] == "1.2.0"
    # The pre-screen's own stamps, as the set they are: every row carries its
    # `fetched_on` and a resumed walk spans days.
    assert manifest["filers"] == {"rows": 2, "vintages": ["2026-09-09"]}
    assert manifest["exported_at"] == date.today().isoformat()


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
def _check(tmp_path: Path, *args: str) -> object:
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
    assert "1 of 7 inputs have moved" in result.output


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
    monkeypatch.setattr(export_module.typer, "secho", lambda text, **_: printed.append(str(text)))
    export_module._print_absence(
        {"what": "prices", "reason": "9 companies have no window", "items": list("ABCDEFGHI")}
    )

    assert printed[1].strip() == "A, B, C, D, E, F, and 3 more"


def test_an_absence_with_no_list_prints_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    from mapf.cli.commands import export as export_module

    printed: list[str] = []
    monkeypatch.setattr(export_module.typer, "secho", lambda text, **_: printed.append(str(text)))
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
