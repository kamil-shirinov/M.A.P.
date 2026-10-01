"""The README and the app's front door make the same headline claim, in the same words.

Two statements of one result drift: one gets softened in an edit and the other does not,
and a reader comparing them sees a project that cannot agree with itself about its own
finding. The door's sentence is the source, because a UI test pins it; the README must
contain it verbatim.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]


def _door_sentence() -> str:
    source = (ROOT / "ui" / "assets" / "js" / "ui" / "front-door.js").read_text(encoding="utf-8")
    found = re.search(r'"(does not beat a plain random walk or GARCH[^"]*)"', source)
    assert found, "the door no longer states the headline"
    return found.group(1)


def test_the_readme_states_the_headline_in_the_doors_words() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert _door_sentence() in readme


def test_the_headline_is_in_the_opening_not_buried() -> None:
    """The first paragraph, before any image or heading."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    opening = readme.split("\n![", 1)[0]
    assert _door_sentence() in opening
