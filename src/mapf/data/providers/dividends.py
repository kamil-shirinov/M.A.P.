"""Ex-dividend lookups for a forecast window (ADR 0013).

Allowed to fail, and expected to. The window is in the future at run time, so an
ex-date inside it may simply not be announced; and Stooq publishes no dividend
data at all. Both cases return `known=False`, which Phase 2 must read as
*unknown* rather than *none*.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import structlog

from mapf.core.models import DividendWindow

_logger = structlog.get_logger(__name__)


class NullDividendSource:
    """Admits it does not know. The honest default when nothing is available."""

    def dividends_in(self, ticker: str, start: date, end: date) -> DividendWindow:
        return DividendWindow(start=start, end=end, known=False, source="none")


def _default_lookup(ticker: str) -> list[tuple[date, float]]:  # pragma: no cover - network
    import yfinance

    series = yfinance.Ticker(ticker).dividends
    return [(index.date(), float(amount)) for index, amount in series.items()]


class YFinanceDividendSource:
    """Reads whatever ex-dates Yahoo already knows about.

    Announced future ex-dates appear here; unannounced ones do not, which is
    precisely why `known` exists as a separate field from an empty `ex_dates`.
    """

    def __init__(self, lookup: Callable[[str], list[tuple[date, float]]] | None = None) -> None:
        self._lookup = lookup or _default_lookup

    def dividends_in(self, ticker: str, start: date, end: date) -> DividendWindow:
        try:
            entries = self._lookup(ticker)
        except Exception as err:  # noqa: BLE001 - a scraper raises anything
            # Never blocks a forecast. An unavailable calendar is "unknown".
            _logger.warning("dividend_lookup_failed", ticker=ticker, error=str(err))
            return DividendWindow(start=start, end=end, known=False, source="lookup_failed")

        inside = [(day, amount) for day, amount in entries if start <= day <= end]
        return DividendWindow(
            start=start,
            end=end,
            ex_dates=tuple(day for day, _ in inside),
            total_amount=round(sum(amount for _, amount in inside), 6),
            known=True,
            source="yfinance_announced",
        )
