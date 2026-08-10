"""Making the quarantine delimiter unrepresentable in untrusted text.

The attack this defends against is the oldest one in prompt injection: untrusted
text contains your own closing delimiter, followed by instructions, and the model
reads everything after it as coming from you.

The textbook defence is a random nonce in the delimiter, so the attacker cannot
know what to close. **That defence is unavailable here.** A fresh nonce per call
means a fresh prompt on every run, which means the cache key changes on every run,
which means DoD criterion 5 — a second `map run` in under two seconds with zero
inference calls — can never pass. The cache is not an optimisation on this
hardware (`CLAUDE.md` §6), so a defence that destroys it is not a defence.

So the delimiter is fixed and public, and safety comes from the other side: the
payload is transformed so that it *cannot contain* the marker. Three steps, in
this order, and the order matters:

1. **NFKC normalise.** Compatibility lookalikes — fullwidth `＜`, and similar —
   collapse into their ASCII equivalents. Done first, they become ordinary
   markers that step 3 removes; done last, or not at all, they pass straight
   through as characters that render like a delimiter but do not match one.
2. **Strip control and format characters.** Beyond hygiene, this removes the
   bidirectional overrides that can make text display in an order different from
   the one the model reads.
3. **Delete every marker, to a fixpoint.** A single pass is not enough:
   `<<<<<<` and `<<END<<<>>>...` style payloads can reassemble a marker out of
   the fragments left behind by one round of replacement. The replacement is
   shorter than the marker, so each pass strictly shrinks the text and the loop
   provably terminates.

What this does **not** defend against, stated plainly: visual lookalikes that NFKC
leaves alone (`⟨⟨⟨` is not `<<<` under any normalisation), and instructions written
in plain prose inside the block. Neither can forge the delimiter, so neither can
escape quarantine — the residual mitigation for both is the template telling the
model that the block is data and never instructions, and placing our own
instruction *after* the block so it is the last thing read.
"""

from __future__ import annotations

import unicodedata
from typing import NamedTuple

from mapf.core.errors import PromptSanitisationError

MARKERS = ("<<<", ">>>")
"""The character sequences the delimiter is built from.

Whole marker sequences are removed rather than only the exact delimiter strings,
so that near-misses like `<<<END UNTRUSTED DATA >>>` — which no exact-match
filter would catch, and which a model may well treat as a delimiter anyway —
cannot survive either.
"""

_REPLACEMENT = " "
"""Shorter than any marker, which is what guarantees the fixpoint loop terminates.

A space rather than an empty string so that removal cannot silently weld two
words together into a third that was never in the source.
"""

_MAX_PASSES = 64
_ALLOWED_CONTROL = frozenset({"\n", "\t"})
_STRIPPED_CATEGORIES = frozenset({"Cc", "Cf", "Co"})


class Sanitised(NamedTuple):
    text: str
    markers_removed: int
    controls_removed: int

    @property
    def was_modified(self) -> bool:
        return bool(self.markers_removed or self.controls_removed)


def neutralise(raw: str) -> Sanitised:
    """Return `raw` with every delimiter marker and control character removed.

    Deterministic: the same input always produces the same output, byte for byte.
    That is a requirement, not a convenience — it is what lets the rendered prompt
    hash to the same cache key on a second run.
    """
    normalised = unicodedata.normalize("NFKC", raw)

    kept = [
        char
        for char in normalised
        if char in _ALLOWED_CONTROL or unicodedata.category(char) not in _STRIPPED_CATEGORIES
    ]
    text = "".join(kept)
    controls_removed = len(normalised) - len(text)

    markers_removed = 0
    for _ in range(_MAX_PASSES):
        before = text
        for marker in MARKERS:
            occurrences = text.count(marker)
            if occurrences:
                markers_removed += occurrences
                text = text.replace(marker, _REPLACEMENT)
        if text == before:
            break
    else:  # pragma: no cover - unreachable while the replacement shrinks the text
        raise PromptSanitisationError(
            f"delimiter markers still present after {_MAX_PASSES} passes; refusing to "
            "render a prompt whose quarantine may not hold"
        )

    return Sanitised(text=text, markers_removed=markers_removed, controls_removed=controls_removed)
