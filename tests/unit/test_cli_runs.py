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
from tests.unit.test_journal import ANCHOR, _Market, _write_run

runner = CliRunner()


def _wire(monkeypatch: pytest.MonkeyPatch, market: object | None = None) -> None:
    from mapf.cli.commands import runs as runs_module

    monkeypatch.setattr(runs_module, "build_market_data", lambda s: market or _Market())


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
    _wire(monkeypatch, _Market(sessions=3))
    runs = tmp_path / "runs"
    _write_run(runs, horizon=60)

    result = _invoke(tmp_path, runs)

    assert "window still open" in result.output


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
    assert body["corpus"][0]["window_elapsed"] is True
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


def test_offline_skips_the_fetch_entirely(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No network in a unit test, and no network for a user who just wants the
    list. The stub records every call it receives."""
    market = _Market()
    _wire(monkeypatch, market)
    runs = tmp_path / "runs"
    _write_run(runs)

    result = _invoke(tmp_path, runs, "--offline")

    assert market.asked == []
    assert "window still open" in result.output


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

    config = _config(tmp_path, user_agent="REPLACE_ME <your.name> <your.email@example.com>")
    result = runner.invoke(app, ["runs", "--runs-dir", str(tmp_path), "--config", str(config)])

    assert result.exit_code == EXIT_CONFIG
    assert "MAP_DATA__SEC__USER_AGENT" in result.output


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
        def get_ohlcv(self, ticker: str, start: date, end: date) -> PriceWindow:
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
