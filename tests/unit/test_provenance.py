"""Which commit produced a run.

A twelve-night corpus that dies and resumes executes its second half under whatever
is checked out then. That is an ordinary thing to happen and an indefensible thing
to be unable to see afterwards, so these assertions are about it being recorded
honestly — including when there is nothing to record.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from mapf.core.provenance import CodeVersion, code_version

SHA = "a" * 40


# ---------------------------------------------------------------------------
# The record itself
# ---------------------------------------------------------------------------
def test_a_clean_checkout_is_reproducible() -> None:
    version = CodeVersion(commit=SHA, dirty=False)
    assert version.reproducible is True
    assert version.describe() == "aaaaaaaaaaaa"


def test_a_dirty_tree_is_not_reproducible_and_says_so() -> None:
    """The commit no longer fully describes what ran, and that must be visible."""
    version = CodeVersion(commit=SHA, dirty=True)
    assert version.reproducible is False
    assert version.describe().endswith("+dirty")


def test_an_unknown_version_is_not_reproducible() -> None:
    version = CodeVersion()
    assert version.reproducible is False
    assert "unknown" in version.describe()


def test_a_malformed_commit_is_rejected() -> None:
    """A truncated or branch-named 'commit' would look like provenance and not be."""
    with pytest.raises(ValidationError):
        CodeVersion(commit="not-a-sha")


# ---------------------------------------------------------------------------
# Reading it from git
# ---------------------------------------------------------------------------
def test_the_repository_reports_a_commit() -> None:
    version = code_version()
    assert version.commit is not None
    assert len(version.commit) == 40


def test_it_matches_what_git_reports() -> None:
    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert code_version().commit == expected


def test_a_directory_outside_a_checkout_records_unknown_rather_than_failing(
    tmp_path: Path,
) -> None:
    """A tarball or a CI image without the repository is not a reason to fail a run
    that would otherwise succeed."""
    version = code_version(tmp_path)
    assert version.commit is None
    assert version.reproducible is False


def test_a_missing_git_binary_records_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", explode)
    code_version.cache_clear()
    try:
        assert code_version(Path("/nonexistent-xyz")).commit is None
    finally:
        code_version.cache_clear()


def test_a_git_failure_records_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Result:
        returncode = 128
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
    code_version.cache_clear()
    try:
        assert code_version(Path("/nonexistent-abc")).commit is None
    finally:
        code_version.cache_clear()


def test_a_short_commit_is_treated_as_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Better no provenance than provenance that will not validate."""

    class _Result:
        returncode = 0
        stdout = "abc123\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
    code_version.cache_clear()
    try:
        assert code_version(Path("/nonexistent-def")).commit is None
    finally:
        code_version.cache_clear()


def test_a_dirty_tree_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class _Result:
        def __init__(self, out: str) -> None:
            self.returncode = 0
            self.stdout = out

    def fake(args: list[str], **kwargs: object) -> _Result:
        calls.append(args)
        return _Result(SHA if "rev-parse" in args else " M src/mapf/x.py\n")

    monkeypatch.setattr(subprocess, "run", fake)
    code_version.cache_clear()
    try:
        assert code_version(Path("/nonexistent-ghi")).dirty is True
    finally:
        code_version.cache_clear()


def test_the_lookup_is_cached_for_the_life_of_the_process() -> None:
    """Committing mid-run changes what git answers but not the code executing, so
    the cached first answer is the accurate one."""
    assert code_version() is code_version()
