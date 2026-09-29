"""Whether a trading session has finished, and what to do with it if it has not.

A daily bar for the current session is not a close. Price providers return one
anyway, updating it as the session runs, and it looks exactly like a settled bar:
same shape, same fields, a `close` that is simply the last trade so far.

`PriceWindow.last_close` takes `bars[-1].close`, so a run made during the session
anchors on an intraday quote while every artifact around it says "close". That is
not a rounding difference. The one live run made at 15:52 ET anchored at 87.33;
the same ticker's settled close for that date was 87.18 — a 0.17 gap, in a
forecast whose scenarios span 2%.

The rule here is deliberately crude: regular US equity hours, 09:30 to 16:00 in
New York, and a bar dated today is unfinished until 16:00 has passed there. It
does not know about holidays or half-days, and it does not need to — dropping a
bar on a day the market never opened costs nothing, because there was no bar.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo

# The exchange's own clock. Fixed offsets would be wrong for seven months of the
# year and, worse, wrong in a way that only shows in March and November.
EXCHANGE_TZ = ZoneInfo("America/New_York")
REGULAR_CLOSE = time(16, 0)


class _Dated(Protocol):
    @property
    def date(self) -> date: ...


def session_has_closed(when: datetime, *, session: date) -> bool:
    """Has `session` finished, as of the instant `when`?

    `when` must be timezone-aware: a naive datetime here would be read in
    whatever zone the machine happens to sit in, which is the class of bug this
    module exists to remove rather than relocate.
    """
    if when.tzinfo is None:
        raise ValueError("session_has_closed needs an aware datetime, not a local one")
    local = when.astimezone(EXCHANGE_TZ)
    if local.date() != session:
        # Any other day is either finished or has not started; both mean the bar
        # dated `session` is not the one being written into right now.
        return local.date() > session
    return local.time() >= REGULAR_CLOSE


def settled[Bar: _Dated](bars: Sequence[Bar], *, now: datetime) -> tuple[Bar, ...]:
    """The bars whose sessions have finished, newest last.

    Only the LAST bar is ever in question. A provider does not hand back an
    unfinished bar from the middle of a series, and trimming on a general
    predicate would quietly drop a bar for a day the exchange was shut while the
    machine's clock said otherwise.
    """
    if not bars:
        return ()
    if session_has_closed(now, session=bars[-1].date):
        return tuple(bars)
    return tuple(bars[:-1])
