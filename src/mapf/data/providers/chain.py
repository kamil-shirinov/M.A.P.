"""Failover across price providers.

A window is served by **exactly one provider or refetched**. Rows are never merged
across providers: a merged series would carry two adjustment vintages and one
label, which is the contamination ADR 0003 exists to prevent, wearing a disguise.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import structlog

from mapf.core.errors import AllMarketDataProvidersFailedError, MarketDataError
from mapf.core.models import PriceWindow
from mapf.core.ports import MarketDataProvider

_logger = structlog.get_logger(__name__)


class ProviderChain:
    """Tries each provider in order and reports which one served."""

    def __init__(self, providers: Sequence[MarketDataProvider]) -> None:
        if not providers:
            raise ValueError("a provider chain needs at least one provider")
        self._providers = tuple(providers)

    @property
    def name(self) -> str:
        """The chain's own label. The *serving* provider is on the returned window,
        which is what the manifest records — a run must say which source it used,
        not merely that a chain was involved."""
        return "+".join(provider.name for provider in self._providers)

    def get_ohlcv(self, ticker: str, start: date, end: date) -> PriceWindow:
        causes: dict[str, BaseException] = {}
        for provider in self._providers:
            try:
                return provider.get_ohlcv(ticker, start, end)
            except MarketDataError as err:
                # Any MarketDataError, not only "unavailable" (ADR 0003 amendment):
                # an empty result from a scraper is indistinguishable from a broken
                # one, and one extra request costs less than a spurious failure.
                causes[provider.name] = err
                _logger.warning(
                    "market_data_failover",
                    provider=provider.name,
                    ticker=ticker,
                    error=str(err),
                    remaining=len(self._providers) - len(causes),
                )
        raise AllMarketDataProvidersFailedError(causes)
