"""`map health` — is the server up, and does it have what we configured?"""

from __future__ import annotations

from pathlib import Path

import typer

from mapf.bootstrap import build_llm_provider
from mapf.cli.app import EXIT_OK, app, handle
from mapf.core.errors import MapError
from mapf.settings import ModelRegistry, load


@app.command()
def health(
    config: Path | None = typer.Option(None, help="Config file to use instead of the default."),
) -> None:
    """Verify the inference server and report which configured models are missing."""
    try:
        settings = load([config] if config else None)
        provider = build_llm_provider(settings)
        available = provider.list_models()
        registry = ModelRegistry(settings.models)

        typer.echo(f"server:  {settings.inference.base_url}")
        typer.echo(f"models:  {len(available)} loaded")

        weak = [info for info in available if info.fingerprint_source != "digest"]
        missing: list[str] = []
        for spec in registry.specs:
            try:
                info = registry.resolve(spec.agent, available)
            except MapError:
                missing.append(f"{spec.agent}: {spec.alias}  MISSING")
                continue
            typer.echo(
                f"  {spec.agent:14} {spec.alias:28} -> {info.id}  [{info.fingerprint_source}]"
            )

        if weak:
            # ADR 0001: the limitation is stated, never hidden.
            typer.secho(
                "note: this backend does not expose a weight digest, so cached results "
                "cannot be pinned to exact weights. Runs will record "
                "fingerprint_source accordingly.",
                fg=typer.colors.YELLOW,
            )
        if missing:
            for line in missing:
                typer.secho(f"  {line}", fg=typer.colors.RED, err=True)
            raise typer.Exit(4)
        typer.secho("all configured models are loaded", fg=typer.colors.GREEN)
        raise typer.Exit(EXIT_OK)
    except MapError as err:
        raise handle(err) from err
