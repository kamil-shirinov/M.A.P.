"""`map prices` — a price series for one ticker, on demand.

The adapter behind this has always been callable outside the pipeline; what did not
exist was a way to *ask* it for a series without producing a forecast. A company
page needs the series before any inference runs, and shelling into `map run` to get
one would spend a model to answer a data question.

**There is no "current price" here, and there cannot be.** yfinance and stooq both
serve daily bars, so the most recent number available is a *close*, on a *trading
date*, which may be several days old across a weekend or a holiday. The JSON pairs
the two in a single object for that reason: a consumer cannot destructure the value
without also receiving the date it belongs to. Emitting a bare `price` field would
be an invitation to label yesterday's close as today's price, and the label would be
wrong in exactly the situations that matter most — a gap, a halt, a stale feed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer

from mapf.bootstrap import build_market_data
from mapf.cli.base import app, fail, handle
from mapf.core.errors import MapError
from mapf.settings import load


@app.command()
def prices(
    ticker: str = typer.Argument(..., help="Ticker to fetch, e.g. AAPL."),
    days: int = typer.Option(180, "--days", help="Calendar days of history to request."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
    config: Path | None = typer.Option(None, help="Config file to use instead of the default."),
) -> None:
    """Fetch a daily price series. No inference, no artifacts, nothing written."""
    try:
        settings = load([config] if config else None)
        if days < 1:
            raise fail(f"--days must be at least 1, got {days}", 2)

        end = datetime.now(UTC).date()
        # Live, not a pinned vintage: this answers "what is the series now", which
        # is the opposite of what scoring needs. A vintage here would serve a
        # months-old snapshot to a page that reads as current.
        window = build_market_data(settings).get_ohlcv(ticker, end - timedelta(days=days), end)

        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "ticker": window.ticker,
                        "provider": window.provider,
                        "adjustment": window.adjustment,
                        "requested_days": days,
                        # Never a bare "price": the value and the session it closed
                        # in travel together or not at all.
                        "last_close": {
                            "close": window.last_close,
                            "trading_date": window.last_trading_date.isoformat(),
                        },
                        "bars": [
                            {
                                "date": bar.date.isoformat(),
                                "open": bar.open,
                                "high": bar.high,
                                "low": bar.low,
                                "close": bar.close,
                                "volume": bar.volume,
                            }
                            for bar in window.bars
                        ],
                    }
                )
            )
            return

        typer.secho(f"{window.ticker}  {len(window.bars)} bars", fg=typer.colors.GREEN)
        typer.echo(f"  provider     {window.provider} ({window.adjustment})")
        typer.echo(f"  requested    {days} calendar days to {end}")
        typer.echo(f"  first bar    {window.bars[0].date}")
        # Phrased as what it is. "Current price" would be a claim about now that a
        # daily bar cannot support.
        # Two decimals to read, full precision in the JSON above: providers serve
        # float32, and 316.2200012207031 is the honest value and an unreadable one.
        typer.echo(f"  last close   {window.last_close:.2f} on {window.last_trading_date}")
    except MapError as err:
        raise handle(err) from err
