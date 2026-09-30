"""Primary price source.

`yfinance` is an unofficial scraper of Yahoo Finance, not a supported API. It
throttles at roughly 950 requests per session and breaks periodically — which is
the entire reason a fallback exists (ADR 0003).

`auto_adjust` is passed explicitly, never left to the default. Its default has
changed across releases, and the two settings mean different things: with it on,
`Close` is dividend-adjusted; with it off, `Close` is split-adjusted only. Relying
on the default would silently change the canonical basis on a dependency upgrade,
which is exactly the contamination ADR 0003 exists to prevent.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date

import pandas as pd

from mapf.core.errors import EmptyPriceWindowError, MarketDataUnavailableError
from mapf.core.models import ADJUSTMENT_BASIS, PriceWindow, Quote
from mapf.data.providers.frames import frame_to_window

NAME = "yfinance"


def _default_download(  # pragma: no cover - network path, exercised by tests/contract
    ticker: str, start: date, end: date
) -> pd.DataFrame:
    import yfinance  # imported lazily so the module is importable without network deps

    frame: pd.DataFrame = yfinance.Ticker(ticker).history(
        start=start.isoformat(),
        # Yahoo's end is exclusive; the caller's is inclusive.
        end=(end + pd.Timedelta(days=1)).isoformat(),
        auto_adjust=False,
        actions=False,
        raise_errors=True,
    )
    return frame


class YFinanceProvider:
    """`MarketDataProvider` over Yahoo Finance."""

    def __init__(self, download: Callable[[str, date, date], pd.DataFrame] | None = None) -> None:
        self._download = download or _default_download

    @property
    def name(self) -> str:
        return NAME

    def get_ohlcv(self, ticker: str, start: date, end: date) -> PriceWindow:
        try:
            frame = self._download(ticker, start, end)
        except Exception as err:  # noqa: BLE001 - a scraper raises anything
            # Deliberately broad. yfinance surfaces HTML parse errors, JSON decode
            # errors, and bare KeyErrors depending on how Yahoo broke that day;
            # enumerating them would be a guess that ages badly. The type is
            # narrowed here instead, and the cause is preserved.
            raise MarketDataUnavailableError(NAME, f"{type(err).__name__}: {err}") from err

        if frame is None or frame.empty:
            raise EmptyPriceWindowError(NAME, ticker)

        return frame_to_window(
            frame,
            ticker=ticker,
            provider=NAME,
            adjustment=ADJUSTMENT_BASIS,
            start=start,
            end=end,
        )


def _default_minutes(ticker: str) -> pd.DataFrame:  # pragma: no cover - network path
    import yfinance

    # Five days of one-minute bars, not one: on a Monday before the open, or the
    # day after a holiday, the last trade is days back, and "1d" can come back empty.
    frame: pd.DataFrame = yfinance.Ticker(ticker).history(
        period="5d",
        interval="1m",
        auto_adjust=False,
        actions=False,
        prepost=False,
        raise_errors=True,
    )
    return frame


class YFinanceQuotes:
    """`QuoteSource` over Yahoo Finance: the last one-minute bar's close and its time.

    A one-minute bar rather than a "regular market price" field because the bar
    carries WHEN, and a price without its time cannot say how old it is. Regular
    hours only: an after-hours print is not the market this page says is open or
    closed. Yahoo's quotes can lag the exchange, and the page says so.
    """

    def __init__(self, minutes: Callable[[str], pd.DataFrame] | None = None) -> None:
        self._minutes = minutes or _default_minutes

    @property
    def name(self) -> str:
        return NAME

    def latest(self, ticker: str) -> Quote:
        try:
            frame = self._minutes(ticker)
        except Exception as err:  # noqa: BLE001 - a scraper raises anything
            raise MarketDataUnavailableError(NAME, f"{type(err).__name__}: {err}") from err
        closes = None if frame is None or frame.empty else frame["Close"].dropna()
        if closes is None or closes.empty:
            raise EmptyPriceWindowError(NAME, ticker)
        stamp = pd.Timestamp(closes.index[-1])
        if stamp.tzinfo is None:
            # Yahoo stamps its bars in the exchange's zone; a bare stamp is read
            # as that zone rather than as whatever this machine's clock is set to.
            stamp = stamp.tz_localize("America/New_York")
        return Quote(
            ticker=ticker,
            price=float(closes.iloc[-1]),
            at=stamp.tz_convert(UTC).to_pydatetime(),
            provider=NAME,
        )
