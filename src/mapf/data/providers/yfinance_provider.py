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
from datetime import date

import pandas as pd

from mapf.core.errors import EmptyPriceWindowError, MarketDataUnavailableError
from mapf.core.models import ADJUSTMENT_BASIS, PriceWindow
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
