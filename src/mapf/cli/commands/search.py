"""`map search` — offline symbol lookup. Never downloads."""

from __future__ import annotations

from pathlib import Path

import typer

from mapf.bootstrap import build_symbol_index
from mapf.cli.app import app, handle
from mapf.core.errors import MapError
from mapf.settings import load


@app.command()
def search(
    query: str = typer.Argument(..., help="Ticker or company name."),
    limit: int = typer.Option(10, help="Maximum candidates to show."),
    config: Path | None = typer.Option(None, help="Config file to use instead of the default."),
) -> None:
    """Search the local symbol index. US-listed companies only."""
    try:
        index = build_symbol_index(load([config] if config else None))
        matches = index.search(query, limit=limit)
        if not matches:
            typer.secho(f"no match for {query!r}", fg=typer.colors.YELLOW)
            typer.echo("Name search covers US-listed companies only; pass a suffixed")
            typer.echo("ticker directly for other venues.")
            raise typer.Exit(0)
        for match in matches:
            symbol = match.symbol
            venue = f" [{symbol.exchange}]" if symbol.exchange else ""
            typer.echo(f"  {symbol.ticker:10} {symbol.name}{venue}   ({match.score:.2f})")
    except MapError as err:
        raise handle(err) from err
