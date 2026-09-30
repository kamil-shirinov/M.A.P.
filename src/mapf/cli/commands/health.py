"""`map health` — is the server up, does it have what we configured, and will it
accept the decode schema?

Never reads through the LLM cache. A health check that passes from a cached
response, while the server is down, is worse than no health check at all.
"""

from __future__ import annotations

from pathlib import Path

import typer

from mapf.bootstrap import build_llm_provider, build_prompts
from mapf.cli.base import EXIT_OK, app, handle
from mapf.core.errors import MapError
from mapf.core.ports import LLMProvider, ModelInfo
from mapf.pipeline.probe import probe_grammar
from mapf.settings import ModelRegistry, load


@app.command()
def health(
    config: Path | None = typer.Option(None, help="Config file to use instead of the default."),
    grammar_probe: bool = typer.Option(
        True,
        "--grammar-probe/--no-grammar-probe",
        help=(
            "Send one minimal constrained request to check the backend accepts the "
            "decode schema. Costs a model load; skip it when you only want the "
            "model list."
        ),
    ),
) -> None:
    """Verify the inference server and report which configured models are missing."""
    try:
        settings = load([config] if config else None)
        # Uncached on purpose — see the module docstring.
        provider = build_llm_provider(settings, cached=False)
        available = provider.list_models()
        registry = ModelRegistry(settings.models)

        typer.echo(f"server:  {settings.inference.base_url}")
        typer.echo(f"models:  {len(available)} loaded")

        weak = [info for info in available if info.fingerprint_source != "digest"]
        missing: list[str] = []
        resolved: dict[str, ModelInfo] = {}
        for spec in registry.specs:
            try:
                info = registry.resolve(spec.agent, available)
            except MapError:
                missing.append(f"{spec.agent}: {spec.alias}  MISSING")
                continue
            resolved[spec.agent] = info
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

        if grammar_probe:
            _report_probe(provider, registry, resolved)

        typer.secho("all configured models are loaded", fg=typer.colors.GREEN)
        raise typer.Exit(EXIT_OK)
    except MapError as err:
        raise handle(err) from err


def _report_probe(
    provider: LLMProvider, registry: ModelRegistry, resolved: dict[str, ModelInfo]
) -> None:
    """Probe on the structuralist model — the only agent that decodes under a grammar."""
    typer.echo("grammar: probing $defs/$ref support (this loads the structuralist model)...")
    result = probe_grammar(
        provider=provider,
        prompts=build_prompts(),
        model=resolved["structuralist"],
        sampling=registry.spec("structuralist").sampling,
    )
    colour = {
        "enforced": typer.colors.GREEN,
        "accepted_not_enforced": typer.colors.YELLOW,
        "rejected": typer.colors.RED,
        "inconclusive": typer.colors.YELLOW,
    }[result.outcome]
    typer.secho(f"  {result.outcome}: {result.detail}", fg=colour)
    if result.remedy:
        typer.secho(f"  fix: {result.remedy}", fg=typer.colors.YELLOW)
    if result.outcome == "rejected":
        raise typer.Exit(4)
