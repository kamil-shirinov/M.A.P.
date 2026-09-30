"""The `map` command, assembled: the app from `mapf.cli.base` with every command
registered on it.

Registration is by import, for its side effects, and it happens only here —
never in `base`, which the commands import. This is also the entry point, and
`main` stays here so that what runs is always the assembled app.
"""

from __future__ import annotations

from mapf.cli.base import (
    EXIT_CONFIG,
    EXIT_DATA,
    EXIT_INFERENCE,
    EXIT_MODEL_OUTPUT,
    EXIT_OK,
    app,
    as_shown,
    exit_code_for,
    fail,
    handle,
    hint_for,
)
from mapf.cli.commands import (  # noqa: F401
    corpus,
    evaluate,
    export,
    health,
    prices,
    run,
    runs,
    search,
    serve,
    symbols,
)

__all__ = [
    "EXIT_CONFIG",
    "EXIT_DATA",
    "EXIT_INFERENCE",
    "EXIT_MODEL_OUTPUT",
    "EXIT_OK",
    "app",
    "as_shown",
    "exit_code_for",
    "fail",
    "handle",
    "hint_for",
    "main",
]


def main() -> None:
    app()
