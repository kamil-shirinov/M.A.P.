"""Which bar a horizon lands on. Pure calendar arithmetic over one price series.

Split out of `scorer` because two callers need it and only one of them is scoring.
The run journal has to ask *has this window elapsed, and on which bar* without
importing anything that can produce a score — an import-linter contract enforces
that, and a transitive path through `scorer` (which imports CRPS, the baselines and
the aggregator) would defeat it while looking harmless.

Nothing here compares a price to a forecast. That is the boundary this module is.
"""

from __future__ import annotations

from datetime import date

from mapf.core.errors import MapError
from mapf.core.models import Bar, PriceWindow


class ScoringError(MapError):
    """An item could not be scored."""


class WindowNotClosedError(ScoringError):
    """The forecast horizon has not elapsed yet.

    Refused rather than skipped: silently dropping unfinished windows would shrink
    the reportable sample without anything saying so.
    """


# Prices should match the forecast's recorded spot to the cent. A tolerance this
# loose only catches genuine drift — a corporate action, a different adjustment
# basis or vintage — rather than float noise. Lives here rather than in `scorer`
# so the run journal can use it: `scorer` reaches the scoring machinery, and the
# journal is forbidden to (ADR 0035).
SPOT_TOLERANCE = 1e-4


def anchor_index(window: PriceWindow, as_of: date) -> int:
    """The index of the session a forecast opens from.

    `as_of` is frequently not a trading day — a corpus item is dated the day after
    its filing, and filings land on Fridays — so the anchor is the last bar on or
    before it. Shared by the return and the bar so the two cannot disagree about
    where the horizon starts.
    """
    bars = window.bars
    index = {bar.date: i for i, bar in enumerate(bars)}
    start = index.get(as_of)
    if start is None:
        earlier = [i for i, bar in enumerate(bars) if bar.date <= as_of]
        if not earlier:
            raise ScoringError(f"no bar on or before {as_of} for {window.ticker}")
        start = max(earlier)
    return start


def realised_bar(window: PriceWindow, as_of: date, horizon_days: int) -> Bar:
    """The bar the horizon closes on — the outcome `realised_return` divides by.

    Split out so it can be pinned and compared without recomputing the return, and
    so the pin names the same bar the score used rather than one derived separately.
    """
    bars = window.bars
    start = anchor_index(window, as_of)
    end = start + horizon_days
    if end >= len(bars):
        raise WindowNotClosedError(
            f"{window.ticker} {as_of}: needs {horizon_days} bars after {bars[start].date}, "
            f"series has {len(bars) - start - 1}"
        )
    return bars[end]
