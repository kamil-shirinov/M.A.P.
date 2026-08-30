"""The per-ticker earnings calendar the multiplier baseline is fitted on.

**Why this is not corpus membership.** The obvious source is the frozen corpus,
which already holds Item 2.02 dates per ticker, needs no network, and cannot shift
between passes. It is also wrong, and wrong in the one direction that matters.

`earnings_multiplier` splits every window in the history into two buckets — those
starting on an earnings date, and everything else — and reports the ratio of their
dispersions. An **incomplete** calendar does not merely shrink the earnings bucket.
Every earnings window it fails to name is sorted into the *ordinary* bucket, which
raises the denominator with exactly the high-dispersion windows the numerator is
supposed to isolate. The ratio is pulled toward 1.0 from both ends at once.

A multiplier pinned near 1.0 is a benchmark that **declines to widen for a scheduled
event** — which is the one thing this baseline exists to do, and losing to it is the
specific finding ADR 0018 wanted. Fitting it on a handful of selected filings would
have produced a baseline that is easy to beat, and easy for a reason invisible in
the result. That is the argument for `arch` over a hand-rolled GARCH
(`baselines.py`), applied to the input rather than the estimator.

So the calendar comes from EDGAR: complete over the fitting window, dated by the
filing itself so point-in-time is a property of the data rather than a convention,
and about 120 requests for the whole corpus.

**Cached, and deliberately not fetched lazily per item.** Scoring touches each
ticker several times, and a calendar refetched per item would be both slow and — if
EDGAR's answer moved between calls — a different benchmark for two items of the same
ticker. One fetch per ticker per range, on disk, keyed by the range it covers.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import structlog

from mapf.core.errors import MapError
from mapf.data.filings import FilingsError

_logger = structlog.get_logger(__name__)

# How far back a calendar is fetched. The multiplier can only use dates that fall
# inside the price history it is fitted on, so anything earlier is a wasted request;
# the margin over `history_days` covers a filer whose quarter lands just outside.
DEFAULT_LOOKBACK_DAYS = 1_100


# A ticker reaches this module from the frozen corpus and from EDGAR's own index,
# and is then used as a FILENAME. Neither source is attacker-controlled today, which
# is an argument about the callers rather than about this function: `Ticker` permits
# any 16 characters after upper-casing, so "../../X" is a valid one and would place
# the cache write outside its directory. Validated at the sink, where the path is
# built, because that is the property being protected.
_SAFE_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,15}$")


class EarningsCalendarError(MapError):
    """A ticker's earnings calendar could not be built."""


class EdgarEarningsCalendar:
    """Item 2.02 dates per ticker, fetched once and served point-in-time.

    `dates_before` is the whole interface, and it takes the as-of date rather than
    only the ticker. Asked for "the ticker's earnings dates" an adapter answers with
    all of them, because that reads as a static property of the company; asked as of
    a date it has to answer a point-in-time question (ADR 0023).
    """

    def __init__(
        self,
        filings: object,
        *,
        cache_dir: Path,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> None:
        self._filings = filings
        self._cache_dir = cache_dir
        self._lookback_days = lookback_days
        # Keyed by ticker, but holding the RANGE it covers as well as the dates.
        # Keyed by ticker alone it would serve a calendar fetched for an early item
        # to a later one whose window reaches past it — and scoring runs in
        # ascending date order, so every later item of a ticker would silently get
        # a truncated calendar. Truncated is the failure this whole adapter exists
        # to avoid: an unnamed earnings window is counted as an ordinary one.
        self._memo: dict[str, tuple[date, date, tuple[date, ...]]] = {}
        self.failures: dict[str, str] = {}

    def dates_before(self, ticker: str, as_of: date) -> tuple[date, ...]:
        """Every Item 2.02 filing date **strictly before** `as_of`.

        A ticker whose calendar cannot be built yields nothing and is recorded in
        `failures`. Empty is a legitimate answer here — the multiplier falls back to
        a neutral 1.0 — but it is the answer that quietly weakens the benchmark, so
        it is counted rather than swallowed.
        """
        try:
            calendar = self._calendar(ticker, as_of)
        except (FilingsError, EarningsCalendarError) as error:
            self.failures.setdefault(ticker, str(error))
            _logger.warning("earnings_calendar_unavailable", ticker=ticker, error=str(error))
            return ()
        return tuple(day for day in calendar if day < as_of)

    def _cache_path(self, ticker: str) -> Path:
        """Where this ticker's calendar is cached, or a refusal.

        Two checks rather than one. The pattern rejects the obvious traversal, and
        the containment check confirms the result actually lands under the cache
        root — a pattern is a claim about what strings look like, and the thing that
        matters is where the write goes.
        """
        if not _SAFE_TICKER.match(ticker):
            raise EarningsCalendarError(
                f"{ticker!r} is not a ticker this cache will build a filename from"
            )
        path = (self._cache_dir / f"{ticker}.json").resolve()
        if not path.is_relative_to(self._cache_dir.resolve()):
            raise EarningsCalendarError(f"{ticker!r} resolves outside the calendar cache")
        return path

    def _calendar(self, ticker: str, as_of: date) -> tuple[date, ...]:
        start = as_of - timedelta(days=self._lookback_days)
        cached = self._memo.get(ticker)
        if cached is not None and cached[0] <= start and cached[1] >= as_of:
            return cached[2]

        path = self._cache_path(ticker)
        loaded = self._read(path, start, as_of)
        if loaded is None:
            loaded = self._fetch(ticker, start, as_of)
            self._write(path, ticker, start, as_of, loaded)
        self._memo[ticker] = (start, as_of, loaded)
        return loaded

    def _fetch(self, ticker: str, start: date, end: date) -> tuple[date, ...]:
        getter = getattr(self._filings, "earnings_dates", None)
        if getter is None:  # pragma: no cover - a wiring error, not a runtime path
            raise EarningsCalendarError("filings source cannot list earnings dates")
        found = tuple(getter(ticker, start, end))
        if not found:
            raise EarningsCalendarError(
                f"EDGAR lists no Item 2.02 filing for {ticker} between {start} and {end}"
            )
        return found

    @staticmethod
    def _read(path: Path, start: date, end: date) -> tuple[date, ...] | None:
        """A cached calendar, but only if it covers the range being asked for.

        A narrower cached range is not a partial answer to a wider question — it is
        a *different* calendar, and reusing it would silently sort the uncovered
        earnings windows into the ordinary bucket.
        """
        if not path.is_file():
            return None
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
            covered_from = date.fromisoformat(body["start"])
            covered_to = date.fromisoformat(body["end"])
            dates = tuple(date.fromisoformat(d) for d in body["dates"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if covered_from > start or covered_to < end:
            return None
        return dates

    @staticmethod
    def _write(path: Path, ticker: str, start: date, end: date, dates: tuple[date, ...]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "ticker": ticker,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "fetched_on": date.today().isoformat(),
                    "dates": [d.isoformat() for d in dates],
                },
                indent=1,
            ),
            encoding="utf-8",
        )
