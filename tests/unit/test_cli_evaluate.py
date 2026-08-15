"""`map evaluate` — the only place scores appear, and the refusals that guard them.

The separation from `map corpus run` is worth nothing if this command answers on a
half-finished band, so the refusals are the substance rather than error handling.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from typer.testing import CliRunner

from mapf.cli.app import app
from mapf.corpus.ledger import Ledger, LedgerEntry
from tests.unit.test_cli import _config
from tests.unit.test_cli_corpus import _frozen

runner = CliRunner()


def _invoke(tmp_path: Path, *args: str, frozen: Path | None = None):  # type: ignore[no-untyped-def]
    return runner.invoke(
        app,
        [
            "evaluate",
            "--frozen",
            str(frozen or _frozen(tmp_path)),
            "--ledger-path",
            str(tmp_path / "ledger.jsonl"),
            "--runs-dir",
            str(tmp_path / "runs"),
            *args,
        ],
    )


def _finish(tmp_path: Path, run_ids: list[UUID] | None = None) -> Ledger:
    """Complete both clean items of the fixture corpus."""
    ledger = Ledger(tmp_path / "ledger.jsonl")
    for i, day in enumerate((date(2026, 2, 1), date(2026, 5, 1))):
        ledger.append(
            LedgerEntry(
                ticker="AAPL",
                band="clean",
                filing_date=day,
                status="complete",
                run_id=run_ids[i] if run_ids else uuid4(),
            )
        )
    return ledger


def _manifest(tmp_path: Path, run_id: UUID, commit: str | None, dirty: bool = False) -> None:
    directory = tmp_path / "runs" / str(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    body: dict[str, object] = {}
    if commit is not None:
        body["code_version"] = {"commit": commit, "dirty": dirty}
    (directory / "manifest.json").write_text(json.dumps(body), encoding="utf-8")


# ---------------------------------------------------------------------------
# The refusal that protects the continuation rule
# ---------------------------------------------------------------------------
def test_an_unfinished_band_is_refused(tmp_path: Path) -> None:
    """Looking at a half-band before deciding whether to run the rest is exactly
    the data-dependent stopping the two-pass design prevents."""
    result = _invoke(tmp_path)
    assert result.exit_code == 8
    assert "REFUSED" in result.output
    assert "outstanding" in result.output


def test_a_partially_finished_band_is_still_refused(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append(
        LedgerEntry(
            ticker="AAPL", band="clean", filing_date=date(2026, 2, 1), status="complete"
        )
    )
    result = _invoke(tmp_path)
    assert result.exit_code == 8


def test_a_declared_single_pass_is_accepted(tmp_path: Path) -> None:
    """A deliberate stop is a legitimate outcome — provided it was declared."""
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append(
        LedgerEntry(
            ticker="AAPL", band="clean", filing_date=date(2026, 2, 1), status="complete"
        )
    )
    result = _invoke(tmp_path, "--declared", "clean_half_1")
    assert result.exit_code == 0
    assert "clean_half_1" in result.output


def test_a_finished_band_reports_every_pass(tmp_path: Path) -> None:
    _finish(tmp_path)
    result = _invoke(tmp_path)
    assert result.exit_code == 0
    assert "clean_half_1" in result.output
    assert "clean_half_2" in result.output


# ---------------------------------------------------------------------------
# Code provenance across a resumed corpus
# ---------------------------------------------------------------------------
def test_a_single_commit_is_reported(tmp_path: Path) -> None:
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40)
    result = _invoke(tmp_path)
    assert result.exit_code == 0
    assert "aaaaaaaaaaaa" in result.output
    assert "2 runs" in result.output


def test_two_commits_refuse_unless_acknowledged(tmp_path: Path) -> None:
    """A resumed corpus spanning commits is sometimes fine and sometimes the
    explanation for everything, so it is surfaced rather than averaged."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40)
    _manifest(tmp_path, ids[1], "b" * 40)
    result = _invoke(tmp_path)
    assert result.exit_code != 0
    assert "more than one code version" in result.output
    assert "aaaaaaaaaaaa" in result.output and "bbbbbbbbbbbb" in result.output


def test_mixed_commits_can_be_scored_when_acknowledged(tmp_path: Path) -> None:
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40)
    _manifest(tmp_path, ids[1], "b" * 40)
    result = _invoke(tmp_path, "--allow-mixed-code")
    assert result.exit_code == 0


def test_a_dirty_tree_is_visible_in_the_report(tmp_path: Path) -> None:
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, "a" * 40, dirty=True)
    result = _invoke(tmp_path)
    assert "+dirty" in result.output


def test_runs_predating_the_field_report_unknown(tmp_path: Path) -> None:
    """The current corpus started before code_version existed; that is recorded as
    unknown rather than retrofitted."""
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    for run_id in ids:
        _manifest(tmp_path, run_id, None)
    result = _invoke(tmp_path)
    assert "predates the field" in result.output


def test_missing_manifests_are_reported_rather_than_assumed(tmp_path: Path) -> None:
    _finish(tmp_path)
    result = _invoke(tmp_path)
    assert "no manifests found" in result.output


def test_an_unreadable_manifest_is_skipped(tmp_path: Path) -> None:
    ids = [uuid4(), uuid4()]
    _finish(tmp_path, ids)
    _manifest(tmp_path, ids[0], "a" * 40)
    broken = tmp_path / "runs" / str(ids[1])
    broken.mkdir(parents=True, exist_ok=True)
    (broken / "manifest.json").write_text("{not json", encoding="utf-8")
    result = _invoke(tmp_path)
    assert result.exit_code == 0
    assert "1 runs" in result.output


# ---------------------------------------------------------------------------
# Argument handling
# ---------------------------------------------------------------------------
def test_a_missing_frozen_corpus_is_a_sentence(tmp_path: Path) -> None:
    result = _invoke(tmp_path, frozen=tmp_path / "absent.json")
    assert result.exit_code != 0
    assert "no frozen corpus" in result.output


def test_an_unknown_band_lists_the_real_ones(tmp_path: Path) -> None:
    result = _invoke(tmp_path, "--band", "nonsense")
    assert result.exit_code == 2
    assert "clean" in result.output


def test_scoring_is_declared_unimplemented_rather_than_faked(tmp_path: Path) -> None:
    """Better an explicit gap than a number nobody can trace to a computation."""
    _finish(tmp_path)
    result = _invoke(tmp_path)
    assert "not yet implemented" in result.output


def test_the_config_option_is_not_required(tmp_path: Path) -> None:
    """Evaluation reads artifacts, not the inference config."""
    _config(tmp_path)
    assert _invoke(tmp_path).exit_code in (0, 8)


def test_a_malformed_frozen_corpus_is_a_sentence(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text('{"corpus": {"nope": 1}}', encoding="utf-8")
    result = _invoke(tmp_path, frozen=broken)
    assert result.exit_code != 0
    assert "not a readable frozen corpus" in result.output


def test_unparseable_json_is_a_sentence(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    result = _invoke(tmp_path, frozen=broken)
    assert "not a readable frozen corpus" in result.output


def test_a_zero_pass_split_is_rejected(tmp_path: Path) -> None:
    result = _invoke(tmp_path, "--passes", "0")
    assert result.exit_code == 2
    assert "at least 1" in result.output


def test_an_unexpected_map_error_arrives_as_a_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CLI is an API: every failure a user can cause must be a sentence and an
    exit code, never a traceback."""
    from mapf.core.errors import SymbolIndexMissingError

    def explode(*args: object, **kwargs: object) -> None:
        raise SymbolIndexMissingError("/tmp/x.sqlite")

    monkeypatch.setattr("mapf.cli.commands.evaluate.require_finished", explode)
    result = _invoke(tmp_path)
    assert result.exit_code != 0
    assert "Traceback" not in result.output
