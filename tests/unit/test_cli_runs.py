"""`map runs` — the journal as a listing.

The command is a printer over `mapf.eval.journal`, so most of the behaviour is
tested there. What these pin is what the *output* is allowed to be: sections that
name their population, an outcome stated as a close on a date, and nowhere a figure
that compares the two or that spans them.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mapf.cli.app import app
from tests.unit.test_cli import _config
from tests.unit.test_journal import ANCHOR, VINTAGE, _Snapshot, _write_run

runner = CliRunner()


def _wire(monkeypatch: pytest.MonkeyPatch, snapshot: object | None = None) -> None:
    from mapf.cli.commands import runs as runs_module

    monkeypatch.setattr(runs_module, "build_price_snapshot", lambda s, v: snapshot or _Snapshot())


def _invoke(tmp_path: Path, runs: Path, *args: str) -> object:
    return runner.invoke(
        app, ["runs", "--runs-dir", str(runs), *args, "--config", str(_config(tmp_path))]
    )


def test_each_population_is_its_own_section_with_its_own_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never a combined total: the journal has no accessor one could come from."""
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    _write_run(runs, source="corpus", ticker="AAA")
    _write_run(runs, source="edgar", ticker="BBB", freeze_version=None)

    result = _invoke(tmp_path, runs)

    assert result.exit_code == 0, result.output
    assert "corpus  (1)" in result.output
    assert "edgar  (1)" in result.output
    assert "(2)" not in result.output


def test_every_section_says_whether_its_runs_are_scoreable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reader should not need the manifest schema to know what is in front of
    them. The edgar legend is the one that matters."""
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    _write_run(runs, source="edgar", freeze_version=None)

    result = _invoke(tmp_path, runs)

    assert "outside the corpus, unscored, never pooled with it" in result.output


def test_an_elapsed_window_prints_a_close_and_a_date_never_a_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The comparison is a score. The listing states both sides and stops."""
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    _write_run(runs, horizon=5)

    result = _invoke(tmp_path, runs)

    assert "outcome    close 206.00 on 2026-08-08" in result.output
    for banned in ("error", "hit", "correct", "accuracy", "crps", "vs "):
        assert banned not in result.output.lower()


def test_an_open_window_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, _Snapshot(sessions=3))
    runs = tmp_path / "runs"
    _write_run(runs, horizon=60)

    result = _invoke(tmp_path, runs)

    assert "horizon has not elapsed yet" in result.output


def test_the_three_scenarios_are_printed_with_their_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    _write_run(runs)

    result = _invoke(tmp_path, runs)

    assert "bullish +0.045@0.25" in result.output
    assert "base_case +0.008@0.60" in result.output
    assert "bearish -0.082@0.15" in result.output


def test_the_json_is_keyed_by_population_so_the_artifact_cannot_be_pooled_either(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    _write_run(runs, source="corpus", ticker="AAA")
    _write_run(runs, source="edgar", ticker="BBB", freeze_version=None)

    result = _invoke(tmp_path, runs, "--json")

    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert set(body) == {"corpus", "edgar"}
    assert body["corpus"][0]["ticker"] == "AAA"
    assert body["edgar"][0]["document_source"] == "edgar"
    assert body["corpus"][0]["anchor_date"] == ANCHOR.isoformat()
    assert body["corpus"][0]["outcome_status"] == "closed"
    assert body["corpus"][0]["outcome"]["trading_date"] == "2026-08-08"


def test_one_population_can_be_asked_for_on_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    _write_run(runs, source="corpus", ticker="AAA")
    _write_run(runs, source="edgar", ticker="BBB", freeze_version=None)

    body = json.loads(_invoke(tmp_path, runs, "--source", "edgar", "--json").output)

    assert set(body) == {"edgar"}
    assert body["edgar"][0]["ticker"] == "BBB"


def test_an_unknown_source_is_refused_rather_than_silently_showing_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    _write_run(runs)

    result = _invoke(tmp_path, runs, "--source", "everything")

    assert result.exit_code == 2
    assert "corpus, edgar, news, unknown" in result.output


def test_a_negative_limit_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch)
    result = _invoke(tmp_path, tmp_path / "runs", "--limit", "-1")

    assert result.exit_code == 2
    assert "0 or more" in result.output


def test_an_empty_snapshot_retrieves_nothing_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pure listing. Reported as "not retrieved", never as an open window: the
    second would be a claim about the calendar nobody asked it to make."""
    snapshot = _Snapshot()
    _wire(monkeypatch, snapshot)
    runs = tmp_path / "runs"
    _write_run(runs)

    result = _invoke(tmp_path, runs, "--snapshot", "")

    assert snapshot.asked == []
    assert "not retrieved (no snapshot named)" in result.output


def test_an_empty_runs_directory_says_so_rather_than_printing_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch)
    result = _invoke(tmp_path, tmp_path / "absent")

    assert result.exit_code == 0
    assert "no readable runs" in result.output


def test_the_limit_reaches_the_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    _write_run(runs, anchor=date(2026, 1, 5), ticker="OLD")
    _write_run(runs, anchor=ANCHOR, ticker="NEW")

    body = json.loads(_invoke(tmp_path, runs, "--limit", "1", "--json").output)

    assert [e["ticker"] for e in body["corpus"]] == ["NEW"]


def test_limit_zero_means_all_of_them(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    _write_run(runs, anchor=date(2026, 1, 5), ticker="OLD")
    _write_run(runs, anchor=ANCHOR, ticker="NEW")

    body = json.loads(_invoke(tmp_path, runs, "--limit", "0", "--json").output)

    assert len(body["corpus"]) == 2


def test_a_config_failure_arrives_as_a_sentence_not_a_traceback(tmp_path: Path) -> None:
    """The journal swallows a provider failure per item, so config is the failure
    that still has to reach the user whole."""
    from mapf.cli.app import EXIT_CONFIG

    # A named config file that does not exist. The SEC placeholder no longer
    # serves here: this command contacts nobody, and refusing it on a
    # credential it never uses is the coupling this test now guards against.
    config = tmp_path / "absent.toml"
    result = runner.invoke(app, ["runs", "--runs-dir", str(tmp_path), "--config", str(config)])

    assert result.exit_code == EXIT_CONFIG
    assert "no configuration file found" in result.output


def test_the_listing_reports_what_it_could_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    _write_run(runs)
    _write_run(runs, manifest=False)

    result = _invoke(tmp_path, runs)

    assert "skipped  1 without artifacts, 0 unreadable" in result.output
    assert "counted before --limit" in result.output


def test_a_clean_directory_says_nothing_about_skipping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    _write_run(runs)

    assert "skipped" not in _invoke(tmp_path, runs).output


def test_a_float32_close_is_rounded_for_reading_but_not_in_the_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real yfinance close reads back as 311.29998779296875. The listing shows a
    price; the artifact keeps what the provider actually served."""
    from datetime import timedelta

    from mapf.core.models import Bar, PriceWindow
    from tests.unit.test_journal import ANCHOR as A

    class _Float32:
        vintage = VINTAGE

        def covering(self, ticker: str, start: date, end: date) -> PriceWindow:
            return PriceWindow(
                ticker=ticker,
                provider="yfinance",
                adjustment="split_adjusted",
                bars=tuple(
                    Bar(
                        date=A + timedelta(days=i),
                        open=300.0,
                        high=312.0,
                        low=299.0,
                        close=311.29998779296875,
                        volume=1,
                    )
                    for i in range(10)
                ),
            )

    _wire(monkeypatch, _Float32())
    runs = tmp_path / "runs"
    _write_run(runs, horizon=5)

    assert "close 311.30 on" in _invoke(tmp_path, runs).output
    body = json.loads(_invoke(tmp_path, runs, "--json").output)
    assert body["corpus"][0]["outcome"]["close"] == 311.29998779296875


def test_the_listing_checks_documents_against_the_frozen_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    run_id = _write_run(runs)
    doc = json.loads((runs / run_id / "forecast.json").read_text())["source_doc_ids"][0]
    frozen = tmp_path / "frozen.json"
    frozen.write_text(
        json.dumps({"exhibits": {"by_accession": {"0000000001-26-000001": {"document_id": doc}}}}),
        encoding="utf-8",
    )

    result = _invoke(tmp_path, runs, "--frozen", str(frozen))

    assert "a frozen exhibit, but not the ledger's run for it" in result.output


def test_a_missing_frozen_record_reads_as_unchecked_not_as_no(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`map runs` must work in a checkout with no corpus at all."""
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    _write_run(runs)

    result = _invoke(tmp_path, runs, "--frozen", str(tmp_path / "absent.json"))

    assert result.exit_code == 0, result.output
    assert "not compared (no frozen corpus or ledger supplied)" in result.output


def test_a_frozen_record_without_exhibits_refuses_rather_than_checking_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty answer would read as "no run uses a frozen exhibit"."""
    _wire(monkeypatch)
    frozen = tmp_path / "frozen.json"
    frozen.write_text(json.dumps({"corpus": {}}), encoding="utf-8")

    result = _invoke(tmp_path, tmp_path / "runs", "--frozen", str(frozen))

    assert result.exit_code == 5
    assert "no exhibits section" in result.output


def test_an_exhibits_section_with_no_accessions_refuses_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The section can be present and hold only the verification metadata. Same
    failure, because the answer would still be an empty set posing as an answer."""
    _wire(monkeypatch)
    frozen = tmp_path / "frozen.json"
    frozen.write_text(json.dumps({"exhibits": {"verified": 709}}), encoding="utf-8")

    result = _invoke(tmp_path, tmp_path / "runs", "--frozen", str(frozen))

    assert result.exit_code == 5
    assert "records no exhibits by accession" in result.output


def test_an_arm_is_called_out_as_not_a_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    _write_run(runs, arm="A")

    result = _invoke(tmp_path, runs)

    assert "arm        A — an ablation run, not a projection" in result.output


def test_a_projection_says_nothing_about_arms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    _write_run(runs)

    assert "an ablation run" not in _invoke(tmp_path, runs).output


def test_a_close_is_shown_as_retrieved_with_its_snapshot_and_the_day_it_was_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run's own vintage ends at its anchor and cannot hold the outcome. Saying
    where this one came from is what keeps it a retrieval rather than a result the
    artifact stored."""
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    _write_run(runs, horizon=5)

    result = _invoke(tmp_path, runs)

    assert "retrieved" in result.output
    assert f"from the {VINTAGE} snapshot" in result.output
    body = json.loads(_invoke(tmp_path, runs, "--json").output)
    outcome = body["corpus"][0]["outcome"]
    assert outcome["snapshot"] == VINTAGE.isoformat()
    assert outcome["provider"] == "yfinance"
    assert outcome["adjustment"] == "split_adjusted"
    assert outcome["retrieved_on"] == date.today().isoformat()


def test_a_run_outside_the_snapshot_keeps_its_row_and_names_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per run, never by omission: a listing that dropped these would report a
    smaller history rather than an incomplete snapshot."""
    _wire(monkeypatch, _Snapshot(holds=("AAPL",)))
    runs = tmp_path / "runs"
    _write_run(runs, ticker="ZZZZ")

    result = _invoke(tmp_path, runs)

    assert "ZZZZ" in result.output
    assert "the snapshot holds no window covering this anchor" in result.output


def test_a_malformed_snapshot_date_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch)

    result = _invoke(tmp_path, tmp_path / "runs", "--snapshot", "last-tuesday")

    assert result.exit_code == 2
    assert "must be a date" in result.output


def _frozen_for(tmp_path: Path, runs: Path, run_id: str) -> Path:
    doc = json.loads((runs / run_id / "forecast.json").read_text())["source_doc_ids"][0]
    path = tmp_path / "frozen.json"
    path.write_text(
        json.dumps({"exhibits": {"by_accession": {"0000000001-26-000001": {"document_id": doc}}}}),
        encoding="utf-8",
    )
    return path


def _ledger_for(tmp_path: Path, run_id: str, *, band: str = "clean") -> Path:
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        json.dumps(
            {
                "ticker": "AAPL",
                "band": band,
                "filing_date": "2026-07-31",
                "status": "complete",
                "run_id": run_id,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_a_panel_item_is_named_and_carries_its_band_and_filing_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    run_id = _write_run(runs)

    result = _invoke(
        tmp_path,
        runs,
        "--frozen",
        str(_frozen_for(tmp_path, runs, run_id)),
        "--ledger-path",
        str(_ledger_for(tmp_path, run_id)),
    )

    assert "corpus     in the pre-registered panel — clean band, filed 2026-07-31" in result.output
    # The relation line never says "scored": a ledger entry promises artifacts
    # exist, and no per-item score is persisted anywhere for this to read. (The
    # section legend above it does describe the panel as what `map evaluate`
    # scores, which is a statement about the population, not about this run.)
    relation_line = next(ln for ln in result.output.splitlines() if "corpus     " in ln)
    assert "scored" not in relation_line


def test_a_repeat_is_distinguished_from_the_ledgers_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    run_id = _write_run(runs)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")

    result = _invoke(
        tmp_path,
        runs,
        "--frozen",
        str(_frozen_for(tmp_path, runs, run_id)),
        "--ledger-path",
        str(empty),
    )

    assert "a frozen exhibit, but not the ledger's run for it" in result.output


def test_a_missing_ledger_leaves_the_relation_to_the_document_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`map runs` must work with no ledger, and an absent one is not evidence that
    a run is not a panel item."""
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    run_id = _write_run(runs)

    result = _invoke(
        tmp_path,
        runs,
        "--frozen",
        str(_frozen_for(tmp_path, runs, run_id)),
        "--ledger-path",
        str(tmp_path / "absent.jsonl"),
    )

    assert result.exit_code == 0, result.output
    assert "a frozen exhibit, but not the ledger's run for it" in result.output


def test_the_json_carries_the_relation_and_the_ledger_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    run_id = _write_run(runs)

    body = json.loads(
        _invoke(
            tmp_path,
            runs,
            "--frozen",
            str(_frozen_for(tmp_path, runs, run_id)),
            "--ledger-path",
            str(_ledger_for(tmp_path, run_id, band="ambiguous")),
            "--json",
        ).output
    )

    entry = body["corpus"][0]
    assert entry["corpus_relation"] == "ledger_item"
    assert entry["ledger_item"] == {
        "ticker": "AAPL",
        "band": "ambiguous",
        "filing_date": "2026-07-31",
    }


def test_neither_map_supplied_reads_as_not_compared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch)
    runs = tmp_path / "runs"
    _write_run(runs)

    result = _invoke(
        tmp_path,
        runs,
        "--frozen",
        str(tmp_path / "absent.json"),
        "--ledger-path",
        str(tmp_path / "absent.jsonl"),
    )

    assert "not compared (no frozen corpus or ledger supplied)" in result.output
