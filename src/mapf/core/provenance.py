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

from mapf.core.models import DomainModel

_GIT_TIMEOUT_S = 5.0


class CodeVersion(DomainModel):
    """The commit a run executed under, and whether the tree was clean."""

    commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    # A dirty tree means the commit does not fully describe what ran. Recorded
    # rather than forbidden: refusing to run on uncommitted changes would make
    # every experiment need a commit first, and the honest alternative is to say so.
    dirty: bool = False

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
    return CodeVersion(commit=commit, dirty=bool(status))
