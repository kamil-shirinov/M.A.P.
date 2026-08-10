"""There must be exactly one way to produce `QuarantinedText`.

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


def test_the_detector_would_notice_a_second_site() -> None:
    """Guards the test itself. A scan that silently matches nothing would pass
    every assertion above while checking nothing at all."""
    assert _construction_sites("QuarantinedText")  # positive control
    assert _construction_sites("NoSuchSymbolAnywhere") == {}  # negative control
