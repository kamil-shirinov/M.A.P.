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

One file is replaced within its day, and only once: a window fetched before 16:30
in New York and read after it (ADR 0040). It is neither the close's day nor its
vintage that changed but the bar the file was waiting for, so the file is refetched
and the superseded one is kept beside it rather than lost.
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
from mapf.core.sessions import settled_since

_logger = structlog.get_logger(__name__)

_PROVIDER_KEY = b"mapf_provider"
_BASIS_KEY = b"mapf_adjustment"
_FETCHED_ON_KEY = b"mapf_fetched_on"
# The instant, not the day: whether a file predates the close is a question about
# the time of day, and `fetched_on` cannot answer it.
_FETCHED_AT_KEY = b"mapf_fetched_at"
# Not `*.parquet`, so `PriceSnapshot`'s glob never offers a superseded file as a window.
_SUPERSEDED_SUFFIX = ".superseded"


def _today() -> date:
    return datetime.now(UTC).date()


def _now() -> datetime:
    return datetime.now(UTC)


def read_fetched_at(path: Path) -> datetime | None:
    """When a stored window was fetched, or `None` if the file does not say.

    A file written before the instant was recorded says nothing, and is reported as
    unknown rather than guessed from its modification time, which a copy or a restore
    resets. Unknown is treated as current by the cache: refetching what cannot be
    shown stale would rewrite every old vintage on first read.
    """
    try:
        import pyarrow.parquet as pq

        raw = (pq.read_schema(path).metadata or {}).get(_FETCHED_AT_KEY)
        stamp = None if raw is None else datetime.fromisoformat(raw.decode("utf-8"))
    except (OSError, ValueError):
        return None
    return stamp if stamp is not None and stamp.tzinfo is not None else None


def read_window(path: Path) -> PriceWindow | None:
    """One stored window, with the provenance the parquet metadata carries.

    Module-level because two readers need it: the cache, and the read-only
    snapshot index below. `provider` comes from the file's own metadata rather
    than from a caller's assumption — a close attributed to the wrong source is
    the kind of error that stays invisible.
    """
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


class PriceSnapshot:
    """Read-only lookup over ONE stored vintage. Never fetches, never writes.

    `ParquetPriceCache` keys on the exact window a caller asked for, which is right
    for reproducing a run and useless for asking a question the run never asked.
    The outcome of a five-session horizon is a bar the run's own snapshot cannot
    contain — it did not exist when that snapshot was taken — so answering it means
    finding a *different* window, stored later, that happens to span the date.

    Hence the search: list what the vintage holds for a ticker, keep the windows
    that contain the range, and take the one reaching furthest forward. Furthest
    rather than first, because a horizon needs bars after the anchor and the widest
    window is the one most likely to have them.

    Returning `None` for "this vintage holds no window covering that range" is the
    point of the class. The caller reports it per item; it is not a fetch trigger,
    and there is no path here that would make it one.
    """

    def __init__(self, cache_dir: Path, vintage: date) -> None:
        self._cache_dir = cache_dir
        self._vintage = vintage

    @property
    def vintage(self) -> date:
        return self._vintage

    def covering(self, ticker: str, start: date, end: date) -> PriceWindow | None:
        directory = self._cache_dir / ticker.upper() / ADJUSTMENT_BASIS / self._vintage.isoformat()
        if not directory.is_dir():
            return None
        best: tuple[date, Path] | None = None
        for path in directory.glob("*.parquet"):
            try:
                first, last = (date.fromisoformat(part) for part in path.stem.split("__"))
            except ValueError:
                # A filename that is not a window is not a window. Skipped rather
                # than raised: one stray file must not blind the whole vintage.
                _logger.warning("snapshot_unparseable_name", path=str(path))
                continue
            if first <= start and last >= end and (best is None or last > best[0]):
                best = (last, path)
        return None if best is None else read_window(best[1])


class ParquetPriceCache:
    """A `MarketDataProvider` decorator that persists windows to parquet."""

    def __init__(
        self,
        inner: MarketDataProvider,
        cache_dir: Path,
        *,
        today: Callable[[], date] = _today,
        now: Callable[[], datetime] = _now,
        frozen: bool = False,
    ) -> None:
        self._inner = inner
        self._cache_dir = cache_dir
        self._today = today
        self._now = now
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
        if cached is not None and not self._settled_since_fetch(path, end):
            return cached

        if self._frozen:
            raise PriceSnapshotIncompleteError(
                ticker, self._today().isoformat(), f"{start.isoformat()}__{end.isoformat()}"
            )
        # A failed fetch raises here, with the stale file still in place: serving it
        # would put an unfinished bar back in front of `settled`, which passes it as
        # a close once 16:30 has gone by. The next call retries.
        window = self._inner.get_ohlcv(ticker, start, end)
        if cached is not None:
            _logger.info("price_cache_refreshed_after_settle", ticker=ticker, path=str(path))
            path.replace(path.with_name(path.name + _SUPERSEDED_SUFFIX))
        self._write(path, window)
        return window

    def _settled_since_fetch(self, path: Path, end: date) -> bool:
        """Has a session this window reaches settled since the file was fetched?

        Never for a frozen vintage: it is read, not refreshed, and a snapshot that
        changed when read would be a different snapshot. Never for a window that
        stops before today, which holds only sessions that had already finished.
        """
        if self._frozen:
            return False
        fetched_at = read_fetched_at(path)
        if fetched_at is None:
            return False
        session = settled_since(fetched_at, now=self._now())
        return session is not None and end >= session

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
        return read_window(path)

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
                _FETCHED_AT_KEY: self._now().isoformat().encode("utf-8"),
            }
        )
        temporary = path.with_suffix(".parquet.tmp")
        pq.write_table(table, temporary)
        temporary.replace(path)
