"""Every command module imports cleanly on its own, whichever comes first.

`mapf.cli.app` used to define the app and register the commands by importing
them, and every command imported `mapf.cli.app`. Importing a command first left
it half-built while the rest were imported, so `export`, which takes names from
`evaluate`, failed whenever `evaluate` came first (Findings #72). The suite never
saw it, because by the time any test ran something had imported the app already.
So each module is imported here in a fresh interpreter, first.
"""

from __future__ import annotations

import pkgutil
import subprocess
import sys

import pytest

import mapf.cli.commands

COMMANDS = sorted(m.name for m in pkgutil.iter_modules(mapf.cli.commands.__path__))


def test_every_command_module_is_found() -> None:
    assert {"evaluate", "export", "runs", "serve"} <= set(COMMANDS)


@pytest.mark.parametrize("name", COMMANDS)
def test_a_command_module_imports_first_in_a_fresh_interpreter(name: str) -> None:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", f"import mapf.cli.commands.{name}"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]


def test_the_assembled_app_has_every_command() -> None:
    """Registration moved out of `base`; the assembly must still carry them all."""
    from typer.testing import CliRunner

    from mapf.cli.app import app

    shown = CliRunner().invoke(app, ["--help"]).output
    for name in ("corpus", "evaluate", "export", "health", "runs", "serve", "symbols"):
        assert name in shown, f"{name} is not registered on the assembled app"
