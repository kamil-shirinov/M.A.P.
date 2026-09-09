"""Persisting a scoring pass, so its numbers can be read without re-running it.

**Transcription, not computation.** Everything written here was already computed
and already printed by `map evaluate`. Nothing is derived on the way to disk; the
summary lines are the exact strings `summarise` produced, passed in rather than
re-generated, so a record cannot disagree with what was reported.

Lives in `corpus` rather than `eval` for the same reason `RealisedPins` does: the
scoring layer takes its IO as injected values and never imports a store.

**Write-once per identity, and the identity is in the filename.**

    <band>.<split>.<vintage>.<forecast_digest[:12]>.json

Append would accumulate near-duplicates a reader has to date-sort and guess
between. Replace would erase what a previous code state produced, which is the
thing this project keeps. So a re-run under the same code, freeze and vintage
writes the same path with identical content — scoring is deterministic given
pinned inputs, so this is idempotent and harmless — while a re-run after any change
to the forecast-governing files lands beside the old record rather than on top of
it. A path that exists with DIFFERENT content is refused, never overwritten: that
is the case where regeneration would quietly rewrite history.

**The holdout is not here and cannot be.** `map evaluate --split holdout` is
refused before anything is computed once the spend is recorded (ADR 0031), and it
is recorded. The holdout's per-item scores were printed once and are gone. What
survives is in `corpus/holdout_spend.jsonl` — tracked, with its git history as the
proof of the single spend. Nothing in this module reads or writes that file.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import date
from pathlib import Path

from mapf.core.errors import MapError
from mapf.eval.scorer import BandScores


class ScoreRecordError(MapError):
    """A scoring record could not be written, or would have been overwritten."""


def _serialise(scores: BandScores) -> list[dict[str, object]]:
    """Every scored item as it stands. `asdict` rather than a hand-written mapping,
    so a field added to `ScoredItem` appears here without anyone remembering to."""
    return [asdict(item) for item in scores.items]


def build_record(
    scores: BandScores,
    *,
    band: str,
    split: str,
    vintage: str,
    scored_on: date,
    summaries: Mapping[str, Sequence[str]],
    identity: Mapping[str, object],
) -> dict[str, object]:
    """The record, assembled from values the caller already holds.

    `identity` carries the freeze and code provenance the CLI has computed for its
    own guards — the same `freeze_digest` and `code_version` it prints — so this
    module never reaches for them and the record cannot describe a different state
    from the one that was scored.
    """
    return {
        "band": band,
        "split": split,
        "vintage": vintage,
        "scored_on": scored_on.isoformat(),
        "n": scores.n,
        # Reported by reason, exactly as the terminal shows them. An item that
        # could not be scored is part of what a scoring pass produced.
        "unscored": dict(sorted(scores.unscored.items())),
        "summaries": {metric: list(lines) for metric, lines in summaries.items()},
        "items": _serialise(scores),
        **dict(identity),
    }


def path_for(directory: Path, record: Mapping[str, object]) -> Path:
    """Content-addressed by what produced it, not by when it was written.

    A dirty tree has no honest forecast digest, so it is named `dirty` — which
    collides with the next dirty-tree run and refuses on differing content, exactly
    as it should: two dirty runs are not distinguishable and must not pretend to be.
    """
    digest = str(record.get("forecast_digest") or "dirty")[:12]
    return directory / f"{record['band']}.{record['split']}.{record['vintage']}.{digest}.json"


def write_once(directory: Path, record: Mapping[str, object]) -> tuple[Path, bool]:
    """Write the record, or confirm the one on disk already says the same thing.

    Returns the path and whether anything was written. Refuses rather than
    overwriting when the existing record differs: that is a regeneration under
    changed conditions, and it belongs beside its predecessor under a different
    identity or nowhere at all.
    """
    path = path_for(directory, record)
    body = json.dumps(record, indent=1, sort_keys=True, default=str)
    if path.is_file():
        if path.read_text(encoding="utf-8") == body:
            return path, False
        raise ScoreRecordError(
            f"{path} already holds a different record for the same band, split, "
            f"vintage and code digest. A scoring pass that produced other numbers "
            f"under an identical identity is a contradiction, not an update; it is "
            f"not overwritten. Move or delete the existing file deliberately."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path, True
