"""Parquet cache for price windows, keyed by vintage.

The trap this exists to make visible: **adjusted prices change retroactively.** A
dividend or split alters the factor applied to every prior close, so the same
ticker over the same range fetched a month apart yields different numbers under
the same naive key. Nothing fails; a backtest quietly mixes vintages and its
scores stop meaning anything (ADR 0012).

So the key carries the vintage:

    {ticker}/{basis}/{fetched_on}/{start}__{end}.parquet

`fetched_on` is a conservative proxy — it forces a refetch on a new day even when
no corporate action occurred, which is nearly always. The precise alternative
needs a corporate-actions table, which Phase 1 defers. Old vintages accumulate
rather than being overwritten, deliberately: an overwritten vintage is an
unreproducible run.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import structlog

from mapf.core.errors import PriceSnapshotIncompleteError
from mapf.core.models import ADJUSTMENT_BASIS, Bar, PriceWindow
from mapf.core.ports import MarketDataProvider

_logger = structlog.get_logger(__name__)

_PROVIDER_KEY = b"mapf_provider"
_BASIS_KEY = b"mapf_adjustment"
_FETCHED_ON_KEY = b"mapf_fetched_on"


def _today() -> date:
    return datetime.now(UTC).date()


class ParquetPriceCache:
    """A `MarketDataProvider` decorator that persists windows to parquet."""

    def __init__(
        self,
        inner: MarketDataProvider,
        cache_dir: Path,
        *,
        today: Callable[[], date] = _today,
        frozen: bool = False,
    ) -> None:
        self._inner = inner
        self._cache_dir = cache_dir
        self._today = today
        # A frozen vintage READS ONLY. Without this the pin is cosmetic: a miss
        # would fetch today's series and store it under the pinned name, which is
        # the calendar-keyed cache wearing a fixed label.
        self._frozen = frozen

    @property
    def name(self) -> str:
        return self._inner.name

    def get_ohlcv(self, ticker: str, start: date, end: date) -> PriceWindow:
        path = self._path(ticker, start, end)
        cached = self._read(path)
        if cached is not None:
            return cached

        if self._frozen:
            raise PriceSnapshotIncompleteError(
                ticker, self._today().isoformat(), f"{start.isoformat()}__{end.isoformat()}"
            )
        window = self._inner.get_ohlcv(ticker, start, end)
        self._write(path, window)
        return window

    # -- paths -------------------------------------------------------------
    def _path(self, ticker: str, start: date, end: date) -> Path:
        return (
            self._cache_dir
            / ticker.upper()
            / ADJUSTMENT_BASIS
            / self._today().isoformat()
            / f"{start.isoformat()}__{end.isoformat()}.parquet"
        )

    # -- io ----------------------------------------------------------------
    def _read(self, path: Path) -> PriceWindow | None:
        if not path.is_file():
            return None
        try:
            import pyarrow.parquet as pq

            table = pq.read_table(path)
            metadata = table.schema.metadata or {}
            frame = table.to_pandas()
        except (OSError, ValueError) as err:
            # A truncated file is a miss, not a crash. Losing a run to a partial
            # write would be worse than one refetch.
            _logger.warning("price_cache_unreadable", path=str(path), error=str(err))
            return None

        return PriceWindow(
            # Ticker, basis and vintage are all encoded in the path, which is
            # what makes two vintages impossible to confuse (ADR 0012).
            ticker=path.parents[2].name,
            provider=metadata.get(_PROVIDER_KEY, b"unknown").decode("utf-8"),
            adjustment=metadata.get(_BASIS_KEY, ADJUSTMENT_BASIS.encode()).decode("utf-8"),
            bars=tuple(
                Bar(
                    date=record["date"],
                    open=float(record["open"]),
                    high=float(record["high"]),
                    low=float(record["low"]),
                    close=float(record["close"]),
                    volume=int(record["volume"]),
                )
                for record in frame.to_dict("records")
            ),
        )

    def _write(self, path: Path, window: PriceWindow) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        path.parent.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame(
            [
                {
                    "date": bar.date,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
                for bar in window.bars
            ]
        )
        table = pa.Table.from_pandas(frame, preserve_index=False)
        table = table.replace_schema_metadata(
            {
                _PROVIDER_KEY: window.provider.encode("utf-8"),
                _BASIS_KEY: window.adjustment.encode("utf-8"),
                _FETCHED_ON_KEY: self._today().isoformat().encode("utf-8"),
            }
        )
        temporary = path.with_suffix(".parquet.tmp")
        pq.write_table(table, temporary)
        temporary.replace(path)
