"""Turning a provider's DataFrame into the canonical `PriceWindow`.

Normalisation happens in the adapter layer, never in the caller (ADR 0003). A
caller that had to know which provider produced a frame would be a caller that can
get it wrong, and the failure — a series that is well-formed but means something
different — has no symptom.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import ValidationError

from mapf.core.errors import EmptyPriceWindowError, MalformedPriceDataError
from mapf.core.models import Bar, PriceWindow

_COLUMNS = ("open", "high", "low", "close", "volume")


def frame_to_window(
    frame: pd.DataFrame,
    *,
    ticker: str,
    provider: str,
    adjustment: str,
    start: date,
    end: date,
) -> PriceWindow:
    """Normalise, clip to the requested range, and validate.

    Clipping matters: providers interpret range endpoints inconsistently — some
    exclusive, some inclusive, some rounded to a week — and a window silently
    wider than requested would make two runs with different providers cover
    different periods while claiming the same one.
    """
    working = frame.copy()
    working.columns = [str(column).strip().lower() for column in working.columns]

    if isinstance(working.index, pd.DatetimeIndex):
        working = working.reset_index()
        working.columns = [str(column).strip().lower() for column in working.columns]

    if "date" not in working.columns:
        raise EmptyPriceWindowError(provider, ticker)

    missing = [column for column in _COLUMNS if column not in working.columns]
    if missing:
        raise EmptyPriceWindowError(provider, ticker)

    working["date"] = pd.to_datetime(working["date"], utc=True, errors="coerce").dt.date
    working = working.dropna(subset=["date", *_COLUMNS])
    working = working[(working["date"] >= start) & (working["date"] <= end)]
    working = working.sort_values("date").drop_duplicates(subset="date", keep="last")

    if working.empty:
        raise EmptyPriceWindowError(provider, ticker)

    # `to_dict("records")` rather than `itertuples`: pandas-stubs types the latter
    # as a union of every dtype it could hold, which no amount of casting makes
    # readable at the call site.
    # Translated at the boundary rather than let out raw: `ProviderChain` catches
    # `MarketDataError`, so a bare `ValidationError` here would escape the failover
    # and end the run with another provider configured and never tried.
    try:
        bars = tuple(
            Bar(
                date=record["date"],
                open=float(record["open"]),
                high=float(record["high"]),
                low=float(record["low"]),
                close=float(record["close"]),
                volume=int(record["volume"]),
            )
            for record in working.to_dict("records")
        )
    except ValidationError as err:
        raise MalformedPriceDataError(provider, ticker, str(err)) from err
    return PriceWindow(
        ticker=ticker,
        provider=provider,
        adjustment=adjustment,  # type: ignore[arg-type]
        bars=bars,
    )
