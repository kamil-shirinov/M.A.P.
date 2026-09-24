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


# ---------------------------------------------------------------------------
# What counts as dirty — Findings #54, applied
# ---------------------------------------------------------------------------
# These run against a REAL repository rather than a monkeypatched `subprocess`.
# The whole change is which pathspec is handed to `git status`, and a fake that
# ignores its arguments would pass whatever the pathspec was.
def _repo(root: Path) -> str:
    """A checkout shaped like this one: forecast roots, a UI folder, and prose."""
    for path, body in {
        "src/mapf/core/thing.py": "VALUE = 1\n",
        "config/default.toml": "[models]\nalias = 'x'\n",
        "ui/assets/js/app.js": "export const a = 1;\n",
        "ui/index.html": "<!doctype html>\n",
        "docs/note.md": "prose\n",
        "README.md": "prose\n",
    }.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q"], cwd=root, check=True)  # noqa: S603, S607
    subprocess.run([*git, "add", "-A"], cwd=root, check=True)  # noqa: S603, S607
    subprocess.run([*git, "commit", "-q", "-m", "in"], cwd=root, check=True)  # noqa: S603, S607
    return subprocess.run(  # noqa: S603, S607
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


def _version(root: Path) -> CodeVersion:
    code_version.cache_clear()
    try:
        return code_version(root)
    finally:
        code_version.cache_clear()


def test_an_edit_under_ui_leaves_the_tree_counted_as_clean(tmp_path: Path) -> None:
    """The front end cannot reach a forecast, and before this it silenced one.

    `ui/` is not importable by the pipeline and is read by no run. Under the old
    whole-tree rule an uncommitted UI file made every forecast produced beside it
    record `forecast_digest: null` — the 208 problem, manufactured by a stylesheet.
    """
    _repo(tmp_path)
    clean = _version(tmp_path)
    assert clean.dirty is False
    assert clean.forecast_digest is not None

    (tmp_path / "ui/assets/js/app.js").write_text("export const a = 2;\n", encoding="utf-8")
    edited = _version(tmp_path)
    assert edited.dirty is False
    assert edited.reproducible is True
    # And the digest is not merely present: it is the SAME one. The UI is outside
    # what is hashed, so an identical digest is the claim being made — these two
    # checkouts are forecast-equivalent.
    assert edited.forecast_digest == clean.forecast_digest


def test_an_edit_under_src_mapf_still_makes_it_dirty(tmp_path: Path) -> None:
    """The narrowing must not reach the roots it was narrowed to."""
    _repo(tmp_path)
    (tmp_path / "src/mapf/core/thing.py").write_text("VALUE = 2\n", encoding="utf-8")
    version = _version(tmp_path)
    assert version.dirty is True
    assert version.forecast_digest is None
    assert version.reproducible is False


def test_config_is_inside_the_dirty_scope_too(tmp_path: Path) -> None:
    """Both roots, not just the code one: a config key changes what was asked."""
    _repo(tmp_path)
    (tmp_path / "config/default.toml").write_text("[models]\nalias = 'y'\n", encoding="utf-8")
    assert _version(tmp_path).dirty is True


def test_prose_outside_the_roots_no_longer_suppresses_the_digest(tmp_path: Path) -> None:
    """The case Findings #54 was written about: a README edit took the identity out
    of an export that the same document described a rule for choosing by."""
    _repo(tmp_path)
    (tmp_path / "README.md").write_text("more prose\n", encoding="utf-8")
    (tmp_path / "docs/note.md").write_text("more prose\n", encoding="utf-8")
    version = _version(tmp_path)
    assert version.dirty is False
    assert version.forecast_digest is not None


def test_an_untracked_file_counts_by_where_it_is(tmp_path: Path) -> None:
    """Untracked is dirty — `git status --porcelain` reports it — and the pathspec
    decides which untracked files are heard. A new module under `src/mapf` is the
    strongest case for refusing: it is code that exists and is in no commit."""
    _repo(tmp_path)
    (tmp_path / "ui/assets/js/new.js").write_text("export const b = 1;\n", encoding="utf-8")
    assert _version(tmp_path).dirty is False

    (tmp_path / "src/mapf/core/new.py").write_text("VALUE = 3\n", encoding="utf-8")
    assert _version(tmp_path).dirty is True


def test_dirt_in_an_excluded_forecast_path_still_suppresses(tmp_path: Path) -> None:
    """NOT_FORECAST_PATHS are left OUT of the hash and left IN the dirty scope.

    Narrowing to the roots is the change Findings #54 argued for. Narrowing further
    — so that an uncommitted `src/mapf/eval/` recorded a digest — is a second
    decision, and nobody has made it. Over-refusing here stays visible.
    """
    _repo(tmp_path)
    evaluate = tmp_path / "src/mapf/eval/aggregate.py"
    evaluate.parent.mkdir(parents=True, exist_ok=True)
    evaluate.write_text("MEAN = 1\n", encoding="utf-8")
    assert _version(tmp_path).dirty is True
