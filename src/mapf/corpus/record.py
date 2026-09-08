"""Reading the frozen record from disk.

`Corpus` is a pure model over the *selection* — no clock, no filesystem — and it
stays that way, so the one piece of I/O it needs lives here instead. This was eight
lines inside `cli/commands/corpus.py`, which put the only read path for the
pre-registration at the top of the import graph: nothing below `mapf.cli` could
open the file that decides what the panel is.
"""

from __future__ import annotations

import json
from pathlib import Path

from mapf.core.errors import MapError


class FrozenRecordError(MapError):
    """The frozen record is missing or unreadable.

    Typed rather than a CLI `fail()` so callers other than the CLI can distinguish
    "no corpus here" from a parse failure in their own terms. The corpus is the
    pre-registration; a caller that cannot read it must stop, never proceed on a
    default.
    """


def load_frozen(path: Path) -> dict[str, object]:
    """The whole record, unvalidated.

    Deliberately the raw mapping rather than a `Corpus`. The file carries fields the
    corpus model does not — `freeze_version`, `prompts`, `truncation`,
    `price_vintage` — and the freeze digest is computed over the record as written,
    so a caller that needs to hash it must see exactly what was on disk.
    """
    if not path.is_file():
        raise FrozenRecordError(f"no frozen corpus at {path}")
    try:
        parsed: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise FrozenRecordError(f"{path} is not valid JSON: {err}") from err
    return parsed
