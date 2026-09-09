"""`map export` — the readable state as flat JSON.

Three properties carry the weight, and none of them is about serialisation:

the shape refuses pooling as firmly as `Journal` does; every absence is a stated
fact in the manifest rather than a missing file; and a held filing nothing ran is
exported with an empty run list, because a page showing 701 of 709 would misstate
the record it is drawing.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapf.cli.app import EXIT_DATA, app
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
    assert manifest["ledger"]["resolved"] == 1
    assert manifest["export_version"] == "1.0.0"
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

    _symbols(tmp_path)
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
    _symbols(tmp_path)
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

    _symbols(tmp_path)
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

    config = _config(tmp_path, user_agent="REPLACE_ME <your.name> <your.email@example.com>")
    result = runner.invoke(
        app, ["export", "--out", str(tmp_path / "export"), "--config", str(config)]
    )

    assert result.exit_code == EXIT_CONFIG
    assert "MAP_DATA__SEC__USER_AGENT" in result.output
