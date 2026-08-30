"""The forecast digest: what a run's forecasts actually depended on (ADR 0026).

The commit is the wrong equality test, because development continues while a corpus
runs and a twelve-night band therefore spans every commit made during it. A guard
that must be overridden on every run is not a guard.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mapf.core.provenance import (
    FORECAST_ROOTS,
    NOT_FORECAST_PATHS,
    CodeVersion,
    _is_forecast_path,
    forecast_digest,
)

REPO = Path(__file__).resolve().parents[2]


def _head() -> str:
    return subprocess.run(  # noqa: S603
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


# ---------------------------------------------------------------------------
# What counts as forecast-producing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [
        "src/mapf/agents/intake.py",
        "src/mapf/pipeline/run.py",
        "src/mapf/prompts/intake.v2.md",
        "src/mapf/providers/openai_compat.py",
        "src/mapf/core/truncation.py",
        "src/mapf/settings/loader.py",
        "src/mapf/bootstrap.py",
        "src/mapf/corpus/runner.py",
        "config/default.toml",
    ],
)
def test_files_that_can_change_a_forecast_are_included(path: str) -> None:
    assert _is_forecast_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "src/mapf/eval/scorer.py",
        "src/mapf/eval/baselines.py",
        "src/mapf/render/chart.py",
        "src/mapf/cli/commands/evaluate.py",
        "src/mapf/corpus/forecasts.py",
        "src/mapf/corpus/passes.py",
        "src/mapf/data/earnings.py",
        "tests/unit/test_scorer.py",
        "M.A.P.-vault/STATE.md",
        "scripts/backfill_forecast_digest.py",
        "README.md",
    ],
)
def test_files_that_run_after_a_forecast_are_excluded(path: str) -> None:
    """Each is provably downstream: it reads finished artifacts and cannot reach back
    into one. Excluding anything else would be a guess."""
    assert not _is_forecast_path(path)


def test_every_exclusion_sits_inside_an_included_root() -> None:
    """An exclusion naming a path the digest never covered would be decoration, and
    would read as protection that is not there."""
    assert all(p.startswith(FORECAST_ROOTS) for p in NOT_FORECAST_PATHS)


# ---------------------------------------------------------------------------
# The digest itself
# ---------------------------------------------------------------------------
def test_the_digest_is_stable_for_a_commit() -> None:
    """It is a function of file contents at a commit and of nothing else — which is
    exactly what makes it recoverable for a run that recorded only its commit."""
    head = _head()
    assert forecast_digest(head, REPO) == forecast_digest(head, REPO)


def test_the_digest_is_a_sha256() -> None:
    digest = forecast_digest(_head(), REPO)
    assert digest is not None
    assert len(digest) == 64
    CodeVersion(commit=_head(), forecast_digest=digest)  # validates the pattern


def test_an_unknown_commit_yields_no_digest_rather_than_a_guess() -> None:
    assert forecast_digest("0" * 40, REPO) is None


def test_a_scoring_only_commit_does_not_move_the_digest() -> None:
    """`ee492d7` added `map evaluate --check`, touching only `eval/`, the evaluate
    command and tests. Its parent produced the same forecasts."""
    a = forecast_digest("6ef0174", REPO)
    b = forecast_digest("ee492d7", REPO)
    assert a is not None
    assert a == b


def test_a_commit_touching_the_pipeline_does_move_the_digest() -> None:
    """`0d78326` changed `pipeline/run.py`, `pipeline/manifest.py` and
    `core/quality.py`. Whether it altered any forecast is undecidable from here —
    which is why the digest reports a difference rather than adjudicating it."""
    assert forecast_digest("0d78326", REPO) != forecast_digest("318250f", REPO)


def test_a_dirty_tree_records_no_digest() -> None:
    """The commit does not describe the files that ran, so any hash taken from it
    would name code that was not executed."""
    version = CodeVersion(commit="a" * 40, dirty=True)
    assert version.forecast_digest is None
    assert not version.reproducible


def test_a_commit_with_no_forecast_paths_yields_no_digest(tmp_path: Path) -> None:
    """A repository with none of the forecast roots has nothing to hash, and an
    empty hash would be a value two unrelated checkouts could share."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)  # noqa: S603, S607
    subprocess.run(  # noqa: S603, S607
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "empty",
        ],
        cwd=tmp_path,
        check=True,
    )
    head = subprocess.run(  # noqa: S603, S607
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert forecast_digest(head, tmp_path) is None
