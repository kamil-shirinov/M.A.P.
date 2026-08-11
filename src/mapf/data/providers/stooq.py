"""Fallback price source: one CSV endpoint, fetched directly.

No `pandas-datareader`. It is a thin wrapper over exactly this URL, intermittently
maintained, and it sits in the *fallback* path — which exists precisely because the
primary is unreliable. Inheriting a second package's failure modes there defeats
the purpose of having a fallback at all.

Stooq publishes **split-adjusted** closes with no dividend adjustment, which is
the canonical basis (ADR 0012). No transformation is needed, and none is invented.
"""

from __future__ import annotations

import io
from datetime import date

import httpx
import pandas as pd

from mapf.core.errors import EmptyPriceWindowError, MarketDataUnavailableError
from mapf.core.models import ADJUSTMENT_BASIS, PriceWindow
from mapf.data.providers.frames import frame_to_window

NAME = "stooq"
BASE_URL = "https://stooq.com/q/d/l/"

# Stooq answers an unknown symbol with a 200 and this body rather than a 404.
_NO_DATA = "no data"


def to_stooq_symbol(ticker: str) -> str:
    """Map a ticker to Stooq's naming.

    US symbols take a `.us` suffix. Anything already carrying a suffix is passed
    through lowercased and unmodified — Stooq's venue codes do not match the
    Yahoo-style suffixes this project accepts (`.L` is `.uk` there), and guessing
    a mapping would silently fetch a different company. Better to let those miss.
    """
    lowered = ticker.strip().lower()
    return lowered if "." in lowered else f"{lowered}.us"


class StooqProvider:
    """`MarketDataProvider` over Stooq's daily CSV endpoint."""

    def __init__(self, client: httpx.Client | None = None, *, timeout_s: float = 30.0) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_s)

    @property
    def name(self) -> str:
        return NAME

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get_ohlcv(self, ticker: str, start: date, end: date) -> PriceWindow:
        params = {
            "s": to_stooq_symbol(ticker),
            "i": "d",
            "d1": start.strftime("%Y%m%d"),
            "d2": end.strftime("%Y%m%d"),
        }
        try:
            response = self._client.get(BASE_URL, params=params)
        except httpx.HTTPError as err:
            raise MarketDataUnavailableError(NAME, f"{type(err).__name__}: {err}") from err

        if not response.is_success:
            raise MarketDataUnavailableError(NAME, f"HTTP {response.status_code}")

        body = response.text
        if _NO_DATA in body[:200].casefold():
            raise EmptyPriceWindowError(NAME, ticker)

        try:
            frame = pd.read_csv(io.StringIO(body))
        except (ValueError, pd.errors.ParserError) as err:
            raise MarketDataUnavailableError(NAME, f"unparseable CSV: {err}") from err

        return frame_to_window(
            frame,
            ticker=ticker,
            provider=NAME,
            adjustment=ADJUSTMENT_BASIS,
            start=start,
            end=end,
        )
