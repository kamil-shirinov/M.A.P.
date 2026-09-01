"""The holdout is spendable exactly once, enforced rather than intended (ADR 0031).

A holdout protects against a result chosen after seeing it. That protection is gone the
moment the numbers are looked at a second time with a changed model in between — and
*intending* to look once is not a mechanism. This project has now watched a rule enforced
by intention fail twice, which is why the clean-tree rule became an assertion too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer

from mapf.cli.commands.evaluate import _record_holdout_spend, _refuse_if_holdout_spent


def test_an_unspent_holdout_passes(tmp_path: Path) -> None:
    _refuse_if_holdout_spent(tmp_path / "absent.jsonl")


def test_an_empty_record_is_not_a_spend(tmp_path: Path) -> None:
    """A file created but never written to must not lock the holdout out."""
    path = tmp_path / "spend.jsonl"
    path.write_text("\n\n", encoding="utf-8")
    _refuse_if_holdout_spent(path)


def test_a_spent_holdout_refuses(tmp_path: Path) -> None:
    path = tmp_path / "spend.jsonl"
    path.write_text(json.dumps({"scored_on": "2026-09-01"}) + "\n", encoding="utf-8")
    with pytest.raises(typer.Exit):
        _refuse_if_holdout_spent(path)


def test_the_refusal_names_what_was_in_place_when_it_was_spent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """So a reader can tell whether the question being asked now is the same one."""
    path = tmp_path / "spend.jsonl"
    path.write_text(
        json.dumps(
            {
                "scored_on": "2026-09-01",
                "forecast_digest": "d" * 64,
                "freeze_version": "2.6.0",
                "calibration": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(typer.Exit):
        _refuse_if_holdout_spent(path)
    out = capsys.readouterr()
    everything = out.out + out.err
    assert "2026-09-01" in everything
    assert "2.6.0" in everything
    assert "none fitted" in everything


def test_the_spend_records_what_produced_it(tmp_path: Path) -> None:
    path = tmp_path / "spend.jsonl"
    _record_holdout_spend(path, band="clean", items=170, record={"freeze_version": "2.6.0"})
    entry = json.loads(path.read_text(encoding="utf-8").strip())
    assert entry["band"] == "clean"
    assert entry["items"] == 170
    assert entry["freeze_version"] == "2.6.0"
    assert entry["calibration"] is None, "no correction is fitted yet, and the record says so"
    assert "scored_on" in entry and "commit" in entry


def test_a_spend_makes_the_next_run_refuse(tmp_path: Path) -> None:
    """The two halves compose: recording is what enforces the refusal."""
    path = tmp_path / "spend.jsonl"
    _record_holdout_spend(path, band="clean", items=1, record={})
    with pytest.raises(typer.Exit):
        _refuse_if_holdout_spent(path)


def test_the_record_is_append_only(tmp_path: Path) -> None:
    """A second spend adds a line rather than replacing one — the history of an
    attempted re-spend is itself worth keeping."""
    path = tmp_path / "spend.jsonl"
    _record_holdout_spend(path, band="clean", items=1, record={})
    _record_holdout_spend(path, band="ambiguous", items=2, record={})
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2
