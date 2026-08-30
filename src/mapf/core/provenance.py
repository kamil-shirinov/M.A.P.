"""Which code produced a run.

The manifest already pins the model fingerprints, the prompt hashes, the sampling
parameters, the price vintage and the adjustment basis — everything about the
*inputs*. It said nothing about the program.

That matters for a corpus that takes twelve nights. If the job dies at item 200 and
resumes, the resumed half executes under whatever commit is checked out then. A
corpus spanning two commits is a perfectly ordinary thing to happen and an
indefensible thing to be unable to see afterwards, so it is recorded per run rather
than assumed constant.

The lookup is cached for the life of the process, deliberately. Committing while a
run is in flight would change what `git rev-parse` answers, but not the code already
imported and executing — so the cached first answer is the accurate one, and a fresh
lookup per run would record a commit that never produced anything.
"""

from __future__ import annotations

import subprocess
from functools import cache
from pathlib import Path

from pydantic import Field

from mapf.core.hashing import sha256_hex
from mapf.core.models import DomainModel

_GIT_TIMEOUT_S = 5.0

# Paths whose contents can change a FORECAST. Everything under `src/mapf` and
# `config` qualifies unless it provably cannot, and the bias is deliberate:
# over-including costs a false refusal, which is visible and recoverable, while
# under-including costs a false claim that two runs are equivalent, which is
# invisible and would sit inside a published result.
FORECAST_ROOTS: tuple[str, ...] = ("config", "src/mapf")

# The exceptions, each provably downstream of every forecast ever written. They run
# after the corpus, read its artifacts, and cannot reach back into one.
NOT_FORECAST_PATHS: tuple[str, ...] = (
    "src/mapf/eval/",  # scoring, baselines, aggregation
    "src/mapf/render/",  # charts, and corpus runs render none (ADR 0019)
    "src/mapf/cli/commands/evaluate.py",
    "src/mapf/corpus/forecasts.py",  # loads finished forecasts for scoring
    "src/mapf/corpus/passes.py",  # the pass boundary, read at scoring time
    "src/mapf/data/earnings.py",  # the calendar the multiplier baseline is fitted on
)

# The granularity is a FILE, not a behaviour, and the difference is worth stating.
# This answers "did any file that can produce a forecast change", not "did the
# forecast-producing behaviour change" — the second is undecidable without running
# both. So adding an unused config key to `config/default.toml` moves the digest even
# though it cannot move a forecast. That is the conservative direction: a false
# refusal is visible and recoverable, a false claim of equivalence is neither.


class CodeVersion(DomainModel):
    """The commit a run executed under, whether the tree was clean, and what of it
    could have changed the forecast."""

    commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    # A dirty tree means the commit does not fully describe what ran. Recorded
    # rather than forbidden: refusing to run on uncommitted changes would make
    # every experiment need a commit first, and the honest alternative is to say so.
    dirty: bool = False
    # A hash over the contents of every file that can produce a forecast (ADR 0026).
    #
    # The commit is the wrong equality test. Development continues while a corpus
    # runs, so a twelve-night band spans every commit made during it — and a check
    # that must be overridden on every run is not a check. The question is not which
    # commit produced an item but whether anything a forecast DEPENDS ON differed,
    # and two runs sharing this digest are forecast-equivalent however many commits
    # separate them.
    #
    # `None` on a dirty tree, where the commit does not describe the working files
    # and no honest digest can be taken from it.
    forecast_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @property
    def reproducible(self) -> bool:
        return self.commit is not None and not self.dirty

    def describe(self) -> str:
        if self.commit is None:
            return "unknown (not a git checkout)"
        return f"{self.commit[:12]}{'+dirty' if self.dirty else ''}"


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _is_forecast_path(path: str) -> bool:
    return path.startswith(FORECAST_ROOTS) and not path.startswith(NOT_FORECAST_PATHS)


def forecast_digest(commit: str, root: Path | None = None) -> str | None:
    """Hash the forecast-producing files as they stood at `commit`.

    Computed from `git ls-tree`, which lists each path beside its **blob hash** —
    and a git blob hash is a hash of the file's contents. So this is a pure function
    of the tree at that commit, which is what makes it recoverable for any run whose
    commit was recorded and whose tree was clean. Backfilling it is computing a
    function of data already written down, not inferring data that was never
    recorded.

    Returns `None` outside a checkout or when the commit is not present — an unknown
    digest, recorded as unknown, rather than a guess.
    """
    where = root or Path(__file__).resolve().parent.parent.parent.parent
    listing = _git(["ls-tree", "-r", commit, "--", *FORECAST_ROOTS], where)
    if listing is None:
        return None
    entries: list[str] = []
    for line in listing.splitlines():
        meta, _, path = line.partition("\t")
        fields = meta.split()
        if len(fields) < 3 or not path or not _is_forecast_path(path):
            continue
        entries.append(f"{path}\0{fields[2]}")
    if not entries:
        return None
    return sha256_hex("\n".join(sorted(entries)).encode("utf-8"))


@cache
def code_version(root: Path | None = None) -> CodeVersion:
    """The current commit and dirty flag, or an empty version outside a checkout.

    Never raises. A missing `git`, an unpacked tarball or a CI image without the
    repository are all ordinary situations, and none of them is a reason to fail a
    run that would otherwise succeed — an unknown version recorded as unknown is
    strictly better than a run that did not happen.
    """
    where = root or Path(__file__).resolve().parent.parent.parent.parent
    commit = _git(["rev-parse", "HEAD"], where)
    if commit is None or len(commit) != 40:
        return CodeVersion()
    status = _git(["status", "--porcelain"], where)
    dirty = bool(status)
    # No digest on a dirty tree: the commit does not describe the files that ran, so
    # any hash taken from it would name code that was not executed.
    digest = None if dirty else forecast_digest(commit, where)
    return CodeVersion(commit=commit, dirty=dirty, forecast_digest=digest)
