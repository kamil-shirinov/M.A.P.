"""`map symbols sync` — the explicit index build.

Separate from `search` on purpose: a search that silently downloads breaks the
offline guarantee, and turns an EDGAR 403 — a ten-minute IP block — into a
mysterious hang inside what looked like a local lookup.
"""

from __future__ import annotations

from pathlib import Path

import typer

from mapf.bootstrap import build_http_client
from mapf.cli.base import app, handle
from mapf.core.errors import MapError
from mapf.data.symbols import Throttle, sync
from mapf.settings import load

symbols_app = typer.Typer(help="Manage the local symbol index.")
app.add_typer(symbols_app, name="symbols")


@symbols_app.command("sync")
def sync_command(
    config: Path | None = typer.Option(None, help="Config file to use instead of the default."),
) -> None:
    """Download the SEC ticker file and rebuild the local index."""
    try:
        settings = load([config] if config else None)
        sec = settings.data.sec
        with build_http_client(settings) as client:
            count = sync(
                sec.symbols_db,
                url=sec.tickers_url,
                user_agent=sec.user_agent,
                client=client,
                throttle=Throttle(sec.requests_per_second),
            )
        typer.secho(f"indexed {count} US-listed symbols -> {sec.symbols_db}", fg=typer.colors.GREEN)
    except MapError as err:
        raise handle(err) from err
