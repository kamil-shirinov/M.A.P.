"""Loading versioned templates and rendering them with quarantine applied.

Templates are package data under `mapf/prompts/*.md`, loaded through
`importlib.resources`, so they travel with an installed wheel rather than
depending on the process happening to run from the repository root.

Two structural decisions carry most of the safety here.

**Role markers are parsed before slots are substituted.** The template is split
into messages first, and only then is content interpolated into each message body.
Untrusted text containing `[[system]]` is therefore literal text inside a message
and cannot create a new one — the message boundaries are already fixed by the time
any untrusted character is seen.

**Substitution is a single non-rescanning pass.** `re.sub` with a callback never
re-examines what the callback returned, so a value containing `{{other_slot}}`
cannot expand a second time. Nothing here uses `str.format`, which would treat
braces in news text as format syntax.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from importlib import resources
from importlib.resources.abc import Traversable

import structlog

from mapf.core.errors import PromptSlotError, TemplateFormatError, TemplateNotFoundError
from mapf.core.hashing import sha256_hex
from mapf.core.models import TrustedText
from mapf.core.ports import Message, RenderedPrompt
from mapf.core.quarantine import QuarantinedText, close_delimiter, open_delimiter

_logger = structlog.get_logger(__name__)

_PACKAGE = "mapf.prompts"

_ROLE_PATTERN = re.compile(r"^\[\[(system|user|assistant)\]\][ \t]*$", re.MULTILINE)
_SLOT_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _parse_sections(text: str, filename: str) -> tuple[tuple[str, str], ...]:
    markers = list(_ROLE_PATTERN.finditer(text))
    if not markers:
        raise TemplateFormatError(
            f"{filename} contains no role markers; expected at least one of "
            "[[system]], [[user]], [[assistant]] alone on a line"
        )
    preamble = text[: markers[0].start()].strip()
    if preamble:
        raise TemplateFormatError(
            f"{filename} has content before its first role marker: {preamble[:80]!r}"
        )

    sections: list[tuple[str, str]] = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        body = text[marker.end() : end].strip("\n")
        if not body.strip():
            raise TemplateFormatError(f"{filename} has an empty [[{marker.group(1)}]] section")
        sections.append((marker.group(1), body))
    return tuple(sections)


class FilePromptStore:
    """A `PromptStore` over the templates shipped with this package."""

    def __init__(self, package: str = _PACKAGE) -> None:
        self._package = package
        self._cache: dict[tuple[str, str], tuple[str, tuple[tuple[str, str], ...]]] = {}

    def _root(self) -> Traversable:
        return resources.files(self._package)

    def available(self) -> tuple[str, ...]:
        return tuple(
            sorted(entry.name for entry in self._root().iterdir() if entry.name.endswith(".md"))
        )

    def digest(self, name: str, version: str) -> str:
        """The template's content hash.

        Public because the corpus runner checks live templates against the hashes
        frozen with the corpus before spending a night on them (ADR 0019 §4). A
        re-versioned prompt invalidates every cache key, so the check is the
        difference between a 35-minute replay and twelve nights.
        """
        return self._load(name, version)[0]

    def _load(self, name: str, version: str) -> tuple[str, tuple[tuple[str, str], ...]]:
        key = (name, version)
        if key in self._cache:
            return self._cache[key]

        filename = f"{name}.{version}.md"
        resource = self._root() / filename
        try:
            raw = resource.read_bytes()
        except (FileNotFoundError, OSError) as err:
            raise TemplateNotFoundError(name, version, self.available()) from err

        digest = sha256_hex(raw)
        sections = _parse_sections(raw.decode("utf-8"), filename)
        self._cache[key] = (digest, sections)
        return self._cache[key]

    def render(
        self,
        name: str,
        version: str,
        *,
        trusted: Mapping[str, TrustedText] | None = None,
        untrusted: Mapping[str, QuarantinedText] | None = None,
    ) -> RenderedPrompt:
        trusted_values = dict(trusted or {})
        untrusted_values = dict(untrusted or {})

        overlap = set(trusted_values) & set(untrusted_values)
        if overlap:
            raise PromptSlotError(
                f"slot(s) {sorted(overlap)} supplied as both trusted and untrusted; "
                "one of the two is a mistake and guessing which would be worse"
            )

        digest, sections = self._load(name, version)
        seen: set[str] = set()
        messages = tuple(
            Message(
                role=role,  # type: ignore[arg-type]
                content=self._substitute(body, trusted_values, untrusted_values, seen),
            )
            for role, body in sections
        )

        unknown = (set(trusted_values) | set(untrusted_values)) - seen
        if unknown:
            raise PromptSlotError(
                f"slot(s) {sorted(unknown)} were supplied but do not appear in "
                f"{name}.{version}.md; the usual cause is a typo"
            )

        return RenderedPrompt(
            template_name=name,
            template_version=version,
            template_sha256=digest,
            messages=messages,
        )

    def _substitute(
        self,
        body: str,
        trusted: Mapping[str, TrustedText],
        untrusted: Mapping[str, QuarantinedText],
        seen: set[str],
    ) -> str:
        def replace(match: re.Match[str]) -> str:
            slot = match.group(1)
            seen.add(slot)
            if slot in trusted:
                return str(trusted[slot])
            if slot in untrusted:
                return self._wrap(slot, untrusted[slot])
            raise PromptSlotError(
                f"template slot {{{{{slot}}}}} was not supplied; rendering it as a "
                "literal placeholder would send '{{" + slot + "}}' to the model as content"
            )

        return _SLOT_PATTERN.sub(replace, body)

    @staticmethod
    def _wrap(slot: str, value: QuarantinedText) -> str:
        """Delimit already-sanitised text.

        The renderer no longer sanitises: it cannot receive anything unsanitised,
        because the type it accepts has no other constructor. This is the
        parse-don't-validate shape — the type proves the work was already done.
        """
        if value.was_modified:
            # Worth seeing. Marker removal in particular is either an injection
            # attempt or a source document doing something odd, and both are things
            # a human should know happened rather than discover in a forecast.
            _logger.warning(
                "untrusted_text_neutralised",
                slot=slot,
                markers_removed=value.markers_removed,
                controls_removed=value.controls_removed,
            )
        return "\n".join((open_delimiter(slot), value.text, close_delimiter(slot)))
