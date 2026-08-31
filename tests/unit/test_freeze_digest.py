"""The freeze digest: which fields decide what an item was asked (ADR 0029).

The freeze *version* is the wrong equality test, for the same reason the commit was.
Amending the record to note the execution order took it from 2.3.0 to 2.4.0 while
every field governing what a model is asked stayed identical — and a restart would
then have split the band across two versions, with no override available. That is
finding #27 from the side it bit last time: a guard that refuses every band.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from mapf.core.provenance import (
    FREEZE_GOVERNING,
    FREEZE_RECORDED_ONLY,
    freeze_differences,
    freeze_digest,
)

REPO = Path(__file__).resolve().parents[2]


def _frozen_at(ref: str) -> dict[str, object] | None:
    out = subprocess.run(  # noqa: S603, S607
        ["git", "show", f"{ref}:corpus/frozen.json"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return json.loads(out.stdout) if out.returncode == 0 else None


def _record(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "freeze_version": "2.4.0",
        "models": {"intake": {"alias": "llama", "temperature": 0.0}},
        "prompts": {"intake": {"sha256": "a" * 64}},
        "truncation": {"head_tokens": 24000},
        "context_tokens": {"intake": 32768},
        "corpus": {"accepted": []},
        "exhibits": {"by_accession": {}},
        "horizon_days": 5,
        "price_vintage": "2026-08-14",
        "kv_cache": "fp16",
        "degeneration_retry": {"penalty": 0.3},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# What must move the digest
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("field", sorted(FREEZE_GOVERNING))
def test_every_governing_field_moves_the_digest(field: str) -> None:
    """Each of these decides what a model was asked, or which population the band
    was drawn from. A change to any of them is a band whose halves differ."""
    changed = _record(**{field: {"altered": True}})
    assert freeze_digest(_record()) != freeze_digest(changed)


@pytest.mark.parametrize("field", sorted(FREEZE_RECORDED_ONLY))
def test_no_recorded_only_field_moves_the_digest(field: str) -> None:
    """Provenance of the record, prose, the band order, the attempt order. Each is
    kept in the record and excluded from the equality test, and each is excluded for
    a reason that can be stated."""
    assert freeze_digest(_record()) == freeze_digest(_record(**{field: "anything"}))


def test_the_two_sets_do_not_overlap() -> None:
    assert not set(FREEZE_GOVERNING) & set(FREEZE_RECORDED_ONLY)


def test_the_real_record_has_no_unclassified_field() -> None:
    """A field in neither list is silently excluded — the under-inclusion direction,
    where a real difference reads as agreement."""
    record = json.loads((REPO / "corpus" / "frozen.json").read_text(encoding="utf-8"))
    unclassified = set(record) - set(FREEZE_GOVERNING) - set(FREEZE_RECORDED_ONLY)
    assert unclassified == set(), f"unclassified frozen fields: {sorted(unclassified)}"


# ---------------------------------------------------------------------------
# Against the real freeze history
# ---------------------------------------------------------------------------
def test_the_execution_order_amendment_did_not_change_the_question() -> None:
    """The case this exists for. 2.3.0 -> 2.4.0 recorded the attempt order and
    nothing else; comparing versions would have refused the band on a restart."""
    before, after = _frozen_at("d79f84d~1"), _frozen_at("d79f84d")
    assert before is not None and after is not None
    assert before["freeze_version"] != after["freeze_version"]
    assert freeze_digest(before) == freeze_digest(after)
    assert freeze_differences(before, after) == []


def test_the_degeneration_retry_amendment_did_change_it() -> None:
    """The control. Without it the assertion above would pass under a digest that
    never fires, which is the failure it is meant to avoid."""
    before, after = _frozen_at("5a139c0~1"), _frozen_at("5a139c0")
    assert before is not None and after is not None
    assert freeze_digest(before) != freeze_digest(after)
    assert set(freeze_differences(before, after)) == {"models", "degeneration_retry"}


def test_the_difference_report_names_the_fields() -> None:
    assert freeze_differences(_record(), _record(horizon_days=21)) == ["horizon_days"]


def test_a_record_with_no_governing_fields_has_no_digest() -> None:
    """An empty hash is a value two unrelated records could share."""
    assert freeze_digest({"freeze_version": "9.9.9"}) is None


def test_the_digest_is_stable_and_order_independent() -> None:
    a = _record()
    b = dict(reversed(list(a.items())))
    assert freeze_digest(a) == freeze_digest(b)


# ---------------------------------------------------------------------------
# Recovering a past record, and failing softly when it cannot be
# ---------------------------------------------------------------------------
def test_a_past_frozen_record_is_recoverable_from_its_commit() -> None:
    """The same recovery argument as the code digest: the freeze a run executed under
    is the one committed alongside the code it recorded."""
    from mapf.cli.commands.evaluate import _frozen_at

    record = _frozen_at("d79f84d")
    assert record is not None
    assert record["freeze_version"] == "2.4.0"


def test_an_unknown_commit_recovers_nothing() -> None:
    from mapf.cli.commands.evaluate import _frozen_at

    assert _frozen_at("0" * 40) is None


def test_a_missing_git_recovers_nothing_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The field list is evidence for a reader, never the thing being decided."""
    from mapf.cli.commands.evaluate import _frozen_at

    monkeypatch.setattr(
        "mapf.cli.commands.evaluate.subprocess.run",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("no git")),
    )
    assert _frozen_at("HEAD") is None


def test_a_malformed_record_recovers_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from mapf.cli.commands.evaluate import _frozen_at

    monkeypatch.setattr(
        "mapf.cli.commands.evaluate.subprocess.run",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="{not json"),
    )
    assert _frozen_at("HEAD") is None


def test_a_record_that_is_not_an_object_recovers_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from mapf.cli.commands.evaluate import _frozen_at

    monkeypatch.setattr(
        "mapf.cli.commands.evaluate.subprocess.run",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="[1,2]"),
    )
    assert _frozen_at("HEAD") is None


def test_a_diff_needs_exactly_two_groups_to_be_meaningful() -> None:
    """With one group there is nothing to compare; with three, no pair is the pair."""
    from mapf.cli.commands.evaluate import _freeze_diff

    assert _freeze_diff({"a": "x"}) == []
    assert _freeze_diff({"a": "x", "b": "y", "c": "z"}) == []
