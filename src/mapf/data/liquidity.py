"""Liquidity screening over the market-data chain.

Selection walks a seeded ordering of every US filer, and most of them are
micro-caps. This is the screen that keeps the corpus inside the asset class the
power analysis was computed for (ADR 0018), applied mechanically rather than by
judgement.

Median rather than mean dollar volume: a single earnings day or an index-inclusion
event can carry a mean over the floor on its own, and a name that is liquid on four
days a year is not a name a forecast window can be scored on.
"""

from __future__ import annotations

import statistics
from datetime import date

import structlog

from mapf.core.errors import MapError, MarketDataError
from mapf.core.ports import MarketDataProvider

_logger = structlog.get_logger(__name__)

# A year has ~252 trading days. A name that traded on far fewer was suspended,
# newly listed, or delisted mid-window — none of which is a candidate, and all of
# which would otherwise pass on a healthy-looking median over a handful of bars.
MIN_BARS = 200


class MarketLiquidity:
    """`LiquidityScreen` over any `MarketDataProvider`."""

    def __init__(self, market: MarketDataProvider, *, min_bars: int = MIN_BARS) -> None:
        self._market = market
        self._min_bars = min_bars

    def median_dollar_volume(self, ticker: str, start: date, end: date) -> float | None:
        try:
            window = self._market.get_ohlcv(ticker, start, end)
        except MarketDataError:
            # Absent history is a legitimate screening answer, not a run failure:
            # selection turns it into a typed rejection with a reason.
            return None
        except MapError:
            _logger.warning("liquidity_screen_failed", ticker=ticker, window=f"{start}..{end}")
            return None

        if len(window.bars) < self._min_bars:
            _logger.debug(
                "liquidity_insufficient_bars",
                ticker=ticker,
                bars=len(window.bars),
                required=self._min_bars,
            )
            return None
        return statistics.median(bar.close * bar.volume for bar in window.bars)
