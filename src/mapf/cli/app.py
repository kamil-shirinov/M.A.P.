"""The `map` command.

Every failure a user can cause is translated into a sentence and an exit code.
Someone who has not started their inference server should be told exactly that —
not handed a traceback through a networking library they did not choose to use.

Exit codes are meaningful because a CLI is also an API:
  0  success
  1  unexpected failure (the traceback is a bug in this program)
  2  usage error (typer's own convention)
  3  configuration is wrong — fix a file or an environment variable
  4  the inference server is not reachable or a model is missing
  5  external data (prices, symbols, news) could not be obtained
  6  the model produced something unusable after every repair attempt
"""

from __future__ import annotations

import typer

from mapf.core.errors import (
    AgentError,
    ConfigurationError,
    InferenceUnreachableError,
    MapError,
    ModelNotAvailableError,
    ProviderError,
    SymbolError,
    SymbolIndexMissingError,
)

EXIT_OK = 0
EXIT_CONFIG = 3
EXIT_INFERENCE = 4
EXIT_DATA = 5
EXIT_MODEL_OUTPUT = 6

app = typer.Typer(
    name="map",
    help="Market's Agentic Projections — calibrated, falsifiable price forecasts.",
    no_args_is_help=True,
    add_completion=False,
)


def as_shown(value: float) -> str:
    """Format a forecast number so the terminal cannot misrepresent the artifact.

    `:+.1f` printed a stored `0.05` as `+0.1` — a doubling, in the direction that
    made a degenerate forecast look merely small. That display sent a real
    diagnosis down the wrong path before anyone read the JSON.

    Four significant figures, not a fixed decimal count: fixed precision always has
    a magnitude at which it rounds a value into a different one, and forecast
    numbers here span three orders of magnitude. A test pins the regression case
    directly.
    """
    return f"{value:+.4g}"


def fail(message: str, code: int, *, hint: str | None = None) -> typer.Exit:
    """Print a sentence, not a traceback."""
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    if hint:
        typer.secho(f"  {hint}", fg=typer.colors.YELLOW, err=True)
    return typer.Exit(code)


def exit_code_for(error: MapError) -> int:
    """Map a typed failure to an exit code. One place, so it cannot drift."""
    if isinstance(error, ModelNotAvailableError | InferenceUnreachableError):
        return EXIT_INFERENCE
    if isinstance(error, ConfigurationError):
        return EXIT_CONFIG
    if isinstance(error, AgentError):
        return EXIT_MODEL_OUTPUT
    if isinstance(error, SymbolError | ProviderError):
        return EXIT_DATA
    return 1


def hint_for(error: MapError) -> str | None:
    """The remedy, where there is exactly one."""
    if isinstance(error, InferenceUnreachableError):
        return (
            "Start your inference server, then check inference.base_url in "
            "config/default.toml points at it. `map health` will confirm."
        )
    if isinstance(error, ModelNotAvailableError):
        return (
            "Load the model in your server, or change the alias in "
            "config/default.toml to one the server actually reports."
        )
    if isinstance(error, SymbolIndexMissingError):
        return "Run `map symbols sync` once to build the local index."
    return None


def handle(error: MapError) -> typer.Exit:
    return fail(str(error), exit_code_for(error), hint=hint_for(error))


def main() -> None:
    app()


# Sub-commands are registered by importing their modules for their side effects.
from mapf.cli.commands import (  # noqa: E402,F401
    corpus,
    evaluate,
    health,
    run,
    search,
    symbols,
)
