"""Recover `forecast_digest` for manifests written before the field existed.

Safe to run repeatedly, and safe to run **while the corpus is running**: it reads
git and rewrites individual manifest files, makes no network call, loads no model,
and never touches the ledger or the cache.

    uv run python scripts/backfill_forecast_digest.py [--dry-run]

WHY THIS IS RECOVERY AND NOT INVENTION

The digest is a pure function of the file contents at a commit, and every manifest
already records the commit its run executed under. `git ls-tree` recovers those
contents exactly. So this computes a function of data that was written down — it does
not infer data that was never recorded, which is the distinction that made inferring
a run's identity from timestamps wrong and makes this right.

**A dirty-tree run stays unknown.** Its commit does not describe the files that ran,
so no honest digest can be taken from it, and it is excluded from the equality check
with that stated rather than being given a plausible-looking value.

A manifest that already carries a digest is left alone: the value written at run time
is the authority, and overwriting it with a recomputation would replace a measurement
with a reconstruction.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

from mapf.core.provenance import forecast_digest
from mapf.corpus.ledger import Ledger
from mapf.settings import load

MANIFEST_VERSION = "1.6.0"


def _write_atomically(path: Path, body: str) -> None:
    """Replace the manifest in one step, never in two.

    The corpus is running while this is used. A plain `write_text` interrupted
    part-way leaves a truncated manifest, and a truncated manifest is an item that
    cannot be audited or scored — recoverable only by re-running it. A temp file in
    the same directory plus `os.replace` is atomic on this filesystem, so a reader
    sees either the old manifest or the new one.
    """
    handle, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(body)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    settings = load()
    runs_dir = settings.paths.runs_dir
    ledger = Ledger(Path("var/corpus/ledger.jsonl"))

    outcomes: Counter[str] = Counter()
    digests: Counter[str] = Counter()
    for entry in ledger.resolved().values():
        if entry.status != "complete" or entry.run_id is None:
            continue
        path = runs_dir / str(entry.run_id) / "manifest.json"
        if not path.is_file():
            outcomes["no manifest"] += 1
            continue
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            outcomes["unreadable"] += 1
            continue

        version = manifest.get("code_version") or {}
        if version.get("forecast_digest"):
            outcomes["already recorded"] += 1
            digests[version["forecast_digest"][:12]] += 1
            continue
        commit = version.get("commit")
        if not commit:
            outcomes["no commit recorded"] += 1
            continue
        if version.get("dirty"):
            # Stays unknown, deliberately. The commit does not describe what ran.
            outcomes["dirty tree — left unknown"] += 1
            continue

        digest = forecast_digest(str(commit))
        if digest is None:
            outcomes["commit not in this checkout"] += 1
            continue

        digests[digest[:12]] += 1
        outcomes["backfilled"] += 1
        if dry_run:
            continue
        version["forecast_digest"] = digest
        manifest["code_version"] = version
        manifest["manifest_version"] = MANIFEST_VERSION
        _write_atomically(path, json.dumps(manifest, indent=2))

    label = "would backfill" if dry_run else "backfilled"
    print(f"{label}:")
    for reason, count in outcomes.most_common():
        print(f"  {count:>4}  {reason}")
    print()
    print(f"distinct forecast digests across the band: {len(digests)}")
    for digest, count in digests.most_common():
        print(f"  {digest}  {count} runs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
