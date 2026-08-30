"""Where each text type may be constructed, pinned so a new site cannot slip in.

There must be exactly one way to produce `QuarantinedText`.

`mypy` stops raw text reaching a prompt through the *type* system, and the
constructor token stops it at runtime. Neither answers the remaining question:
has someone added a second construction site somewhere in `src/`?

This test does. It parses every module under `src/` and asserts the sanitiser is
the only place the type is constructed. It is the same class of enforcement as
`import-linter` and the vendor-string scan — mechanical, visible in a diff, and
run in CI — and it is what makes ADR 0005's claim structural rather than a comment.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
SRC = REPO_ROOT / "src"

SOLE_CONSTRUCTION_SITE = "mapf/core/quarantine.py"


def _construction_sites(name: str) -> dict[str, int]:
    """Files under `src/` that call `name(...)`, and how many times."""
    sites: dict[str, int] = {}
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        calls = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == name)
                or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
            )
        )
        if calls:
            sites[str(path.relative_to(SRC))] = calls
    return sites


def test_quarantined_text_is_constructed_in_exactly_one_place() -> None:
    sites = _construction_sites("QuarantinedText")
    assert list(sites) == [SOLE_CONSTRUCTION_SITE], (
        "QuarantinedText must be constructed only by the sanitiser. A second site "
        "means raw feed text can be labelled as sanitised without being sanitised "
        f"(ADR 0005). Found: {sites}"
    )


def test_the_construction_token_never_leaves_its_module() -> None:
    """Referencing the token elsewhere would reopen the hole from the other side."""
    offenders = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if "_CONSTRUCTOR_TOKEN" in path.read_text(encoding="utf-8")
        and str(path.relative_to(SRC)) != SOLE_CONSTRUCTION_SITE
    ]
    assert offenders == []


UNTRUSTED_TEXT_SITES = {
    # Where raw feed text formally enters the system.
    "mapf/data/news.py",
    # Where filed exhibit text enters. An SEC filing is authoritative about what a
    # company said, which is not the same as being safe to interpolate: it is
    # attacker-influenced prose that reaches a model, so it is tainted like any feed.
    "mapf/data/exhibits.py",
    # Where taint propagates: a truncated exhibit is still filed text, and
    # returning a bare str here would push re-labelling onto every caller —
    # one that forgot would silently launder untrusted text into trusted.
    "mapf/core/truncation.py",
    # Where taint propagates: model output derived from feed text, which is
    # interpolated into the next agent's prompt (ADR 0005).
    "mapf/agents/intake.py",
    "mapf/agents/analyst.py",
}


def test_untrusted_text_is_constructed_only_where_taint_enters_or_propagates() -> None:
    """`UntrustedText` is freely constructible by design — it marks provenance, not
    safety. What must not drift is *where* raw text is labelled, because every one
    of those sites is a place a human decided something was untrusted."""
    assert set(_construction_sites("UntrustedText")) == UNTRUSTED_TEXT_SITES


TRUSTED_TEXT_SITES = {
    # Field labels the pipeline already holds: a ticker, a date, a horizon. None
    # originates outside the system.
    "mapf/agents/intake.py",
    "mapf/agents/analyst.py",
    # The repair loop's attempt index, and pydantic's own messages. The subtle one:
    # `_format_errors` deliberately drops each error's `input`, because that value
    # is model output derived from untrusted news. See the audit's finding #11 for
    # the channel it does NOT drop — an extra-field error's `loc` is the model's own
    # key, and it reaches this slot undelimited.
    "mapf/agents/structuralist.py",
}


def test_trusted_text_is_constructed_only_where_the_pipeline_owns_the_value() -> None:
    """`TrustedText` is the LAUNDERING direction, and it was the one not pinned.

    `UntrustedText` marks something as tainted, which is the safe mistake to make.
    `TrustedText(document.text)` type-checks and silently promotes filed text into
    a slot rendered without quarantine delimiters. Seven sites existed and none was
    asserted, so a new one would have reached CI green (ADR 0022).
    """
    assert set(_construction_sites("TrustedText")) == TRUSTED_TEXT_SITES


def test_no_module_that_handles_untrusted_text_also_mints_trusted_text() -> None:
    """The two sets may overlap only in `agents/`, where an agent legitimately
    labels its own inputs trusted and its own output untrusted. Anywhere else, one
    module doing both is where a promotion would hide."""
    both = set(_construction_sites("TrustedText")) & set(_construction_sites("UntrustedText"))
    assert all(site.startswith("mapf/agents/") for site in both), both


def test_the_detector_would_notice_a_second_site() -> None:
    """Guards the test itself. A scan that silently matches nothing would pass
    every assertion above while checking nothing at all."""
    assert _construction_sites("QuarantinedText")  # positive control
    assert _construction_sites("UntrustedText")  # positive control
    assert _construction_sites("TrustedText")  # positive control
    assert _construction_sites("NoSuchSymbolAnywhere") == {}  # negative control
