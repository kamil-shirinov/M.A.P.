"""Untrusted text, and the only way to make it safe to interpolate.

`UntrustedText` (in `models`) marks **provenance**: this string came from outside,
or was derived from something that did. It says nothing about whether the string
is safe to put in a prompt, and — being a `NewType` — it can be constructed
anywhere, by anyone.

`QuarantinedText` marks a **guarantee**: this string has been through `quarantine`
and provably cannot contain a delimiter marker. It is a real class with a
module-private construction token, so `QuarantinedText("<<<...")` raises rather
than quietly producing an object that lies about what it is. `PromptStore.render`
accepts only this type in its untrusted map, which is what makes a future module
*unable* to interpolate raw feed text rather than merely discouraged from it
(ADR 0005).

Two levels of enforcement, and neither is a runtime sandbox:

- **mypy** rejects `str` and `UntrustedText` where `QuarantinedText` is required;
  distinct types over the same base are mutually unassignable.
- **A test** walks every module under `src/` and asserts this file is the only
  place `QuarantinedText` is constructed. Determined code can still import the
  token — Python has no private constructors — but it cannot happen by accident,
  and it cannot happen without showing up in a diff and failing CI.

This module lives in `core` rather than in `prompts` for one structural reason:
the type and its sole constructor must be co-located, or the token has to be
exported and the guarantee evaporates. The delimiters live here for the same
reason — the sanitiser and the format it protects cannot be allowed to drift
apart. Everything here is pure string work, so `core`'s no-I/O rule holds.

The sanitising argument itself — why fixed delimiters rather than a nonce, and why
the three steps run in this order — is ADR 0009.
"""

from __future__ import annotations

import unicodedata
from typing import Final

MARKERS: Final = ("<<<", ">>>")
"""The character sequences the delimiter is built from.

Whole marker sequences are removed rather than only the exact delimiter strings,
so near-misses like `<<<END UNTRUSTED DATA >>>` — which no exact-match filter
would catch, and which a model may well honour anyway — cannot survive either.
"""

_REPLACEMENT: Final = " "
"""Shorter than any marker, which is what guarantees the fixpoint loop terminates.

A space rather than an empty string, so removal cannot weld two words together
into a third that was never in the source.
"""

_MAX_PASSES: Final = 64
_ALLOWED_CONTROL: Final = frozenset({"\n", "\t"})
_STRIPPED_CATEGORIES: Final = frozenset({"Cc", "Cf", "Co"})

_CONSTRUCTOR_TOKEN: Final = object()


def open_delimiter(slot: str) -> str:
    return f"<<<BEGIN UNTRUSTED DATA: {slot}>>>"


def close_delimiter(slot: str) -> str:
    return f"<<<END UNTRUSTED DATA: {slot}>>>"


class QuarantinedText:
    """Text that provably cannot contain a delimiter marker.

    Constructible only by `quarantine`. The token check is not decoration: without
    it this is a `NewType` in a trench coat, and the guarantee reduces to a comment.
    """

    __slots__ = ("_controls_removed", "_markers_removed", "_text")

    def __init__(
        self,
        text: str,
        markers_removed: int,
        controls_removed: int,
        *,
        _token: object = None,
    ) -> None:
        if _token is not _CONSTRUCTOR_TOKEN:
            raise TypeError(
                "QuarantinedText cannot be constructed directly. It is produced only by "
                "mapf.core.quarantine.quarantine(), which is what guarantees the text "
                "cannot contain a quarantine delimiter. Constructing one by hand would "
                "let raw feed text reach a prompt while claiming it had been sanitised "
                "(ADR 0005, ADR 0009)."
            )
        self._text = text
        self._markers_removed = markers_removed
        self._controls_removed = controls_removed

    @property
    def text(self) -> str:
        return self._text

    @property
    def markers_removed(self) -> int:
        return self._markers_removed

    @property
    def controls_removed(self) -> int:
        return self._controls_removed

    @property
    def was_modified(self) -> bool:
        return bool(self._markers_removed or self._controls_removed)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, QuarantinedText):
            return NotImplemented
        return self._text == other._text

    def __hash__(self) -> int:
        return hash(self._text)

    def __repr__(self) -> str:
        # Deliberately does not include the text. News text can be long, and a repr
        # that dumps it into a log or a traceback is a quiet way to leak a corpus.
        return f"QuarantinedText(<{len(self._text)} chars>)"


def quarantine(raw: str) -> QuarantinedText:
    """Make `raw` safe to interpolate into a prompt (ADR 0009).

    Deterministic and idempotent: identical input always produces identical output,
    byte for byte. That is a requirement rather than a nicety — it is what lets the
    rendered prompt hash to the same cache key on a second run, and therefore what
    keeps DoD criterion 5 reachable.
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
        raise ValueError(
            f"delimiter markers still present after {_MAX_PASSES} passes; refusing to "
            "produce text whose quarantine may not hold"
        )

    return QuarantinedText(
        text,
        markers_removed,
        controls_removed,
        _token=_CONSTRUCTOR_TOKEN,
    )
