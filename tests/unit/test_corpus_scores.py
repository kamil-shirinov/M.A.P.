"""Persisting a scoring pass.

The behaviour worth pinning is not the serialisation — it is what happens on a
second run. A record that can be silently replaced is not a record, and the two
cases a re-run can produce are opposite: identical numbers under an identical
identity are harmless, while different numbers under an identical identity are a
contradiction and must not be written over the top of their predecessor.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from mapf.corpus.scores import ScoreRecordError, build_record, path_for, write_once
from mapf.eval.scorer import BandScores
from tests.unit.test_scorer import _scored

IDENTITY = {
    "commit": "d8c57c31",
    "forecast_digest": "2eb1a29ed862aaaa",
    "freeze_version": "2.6.0",
    "freeze_digest": "7cf4ae3de9a2",
}


def _record(**overrides: object) -> dict[str, object]:
    body = build_record(
        BandScores(items=(_scored(),), unscored={"SpotDriftError": 3}),
        band="clean",
        split="dev",
        vintage="2026-09-05",
        scored_on=date(2026, 9, 9),
        summaries={"crps": ("M.A.P. vs garch: indistinguishable at n=1",)},
        identity=IDENTITY,
    )
    body.update(overrides)
    return body


def test_the_filename_is_what_produced_the_numbers(tmp_path: Path) -> None:
    """Band, split, vintage and code digest — not a timestamp. Two passes that
    differ in any of them are different records; two that differ in none are the
    same record."""
    assert path_for(tmp_path, _record()).name == "clean.dev.2026-09-05.2eb1a29ed862.json"


def test_a_dirty_tree_is_named_dirty_rather_than_given_a_digest(tmp_path: Path) -> None:
    """It has no honest digest. Naming it `dirty` makes the next dirty-tree run
    collide with it — which is right: two dirty runs are not distinguishable and
    must not pretend to be."""
    assert path_for(tmp_path, _record(forecast_digest=None)).name.endswith(".dirty.json")


def test_the_record_carries_the_numbers_and_the_identity(tmp_path: Path) -> None:
    path, written = write_once(tmp_path, _record())

    assert written is True
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["n"] == 1
    assert body["unscored"] == {"SpotDriftError": 3}
    assert body["summaries"]["crps"] == ["M.A.P. vs garch: indistinguishable at n=1"]
    assert body["freeze_digest"] == "7cf4ae3de9a2"
    assert body["commit"] == "d8c57c31"
    assert len(body["items"]) == 1


def test_every_field_of_a_scored_item_travels_without_being_listed(tmp_path: Path) -> None:
    """`asdict`, not a hand-written mapping: a field added to ScoredItem appears
    here without anyone remembering to add it, and a field renamed cannot silently
    keep its old name in the file."""
    from dataclasses import fields

    from mapf.eval.scorer import ScoredItem

    path, _ = write_once(tmp_path, _record())
    stored = json.loads(path.read_text(encoding="utf-8"))["items"][0]

    assert set(stored) == {f.name for f in fields(ScoredItem)}


def test_rerunning_an_identical_pass_writes_nothing_and_does_not_complain(
    tmp_path: Path,
) -> None:
    """Scoring is deterministic given pinned inputs, so this is the normal case."""
    first, written_first = write_once(tmp_path, _record())
    second, written_second = write_once(tmp_path, _record())

    assert first == second
    assert written_first is True
    assert written_second is False


def test_different_numbers_under_the_same_identity_are_refused(tmp_path: Path) -> None:
    """The case the whole scheme exists for. Same band, split, vintage and code
    digest, different scores: one of them is wrong, and overwriting would destroy
    the evidence of which."""
    write_once(tmp_path, _record())

    with pytest.raises(ScoreRecordError, match="already holds a different record"):
        write_once(tmp_path, _record(n=999))


def test_a_changed_code_digest_lands_beside_its_predecessor(tmp_path: Path) -> None:
    """Not on top of it. A re-run after a change to the forecast-governing files
    produced different numbers for a reason, and both are worth keeping."""
    first, _ = write_once(tmp_path, _record())
    second, written = write_once(tmp_path, _record(forecast_digest="ffffffffffff", n=2))

    assert written is True
    assert first != second
    assert {p.name for p in tmp_path.iterdir()} == {first.name, second.name}


def test_the_directory_is_created_on_first_write(tmp_path: Path) -> None:
    nested = tmp_path / "var" / "corpus" / "scores"
    path, _ = write_once(nested, _record())

    assert path.is_file()


def test_the_spend_ledger_is_mentioned_only_in_prose_never_in_code() -> None:
    """The holdout's per-item scores are gone, and this module is not a route back
    to them: `map evaluate --split holdout` is refused before anything is computed
    (ADR 0031). What survives is `corpus/holdout_spend.jsonl`, tracked, with its git
    history as the record of the single spend.

    Asserted structurally rather than by grepping the file: every string literal
    that is not a docstring must be free of it, so the name can stay in the
    documentation — where it belongs — while no expression can reach the path.
    """
    import ast

    tree = ast.parse(Path("src/mapf/corpus/scores.py").read_text(encoding="utf-8"))
    docstrings = {
        # `clean=False`: the cleaned form re-indents, and would never match the
        # raw literal it came from.
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef)
    }
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]

    assert any(d and "holdout_spend" in d for d in docstrings)
    assert not [text for text in literals if "holdout_spend" in text and text not in docstrings]
