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
# The bell is not the close. The official closing price comes out of the closing
# auction and can post several minutes after 16:00, and a provider's bar for the
# day can keep moving until it does. Half an hour of margin costs a run made at
# 16:10 its same-day anchor, which it had no business having anyway.
SETTLED_AFTER = time(16, 30)


class _Dated(Protocol):
    @property
    def date(self) -> date: ...


def session_has_settled(when: datetime, *, session: date) -> bool:
    """Is `session`'s close final, as of the instant `when`?

    Final means 16:30 in New York, not 16:00: the bell ends trading, the closing
    auction sets the price, and the price can reach a provider minutes later.

    `when` must be timezone-aware: a naive datetime here would be read in
    whatever zone the machine happens to sit in, which is the class of bug this
    module exists to remove rather than relocate.
    """
    if when.tzinfo is None:
        raise ValueError("session_has_settled needs an aware datetime, not a local one")
    local = when.astimezone(EXCHANGE_TZ)
    if local.date() != session:
        # Any other day is either finished or has not started; both mean the bar
        # dated `session` is not the one being written into right now.
        return local.date() > session
    return local.time() >= SETTLED_AFTER


def settled[Bar: _Dated](bars: Sequence[Bar], *, now: datetime) -> tuple[Bar, ...]:
    """The bars whose sessions have finished, newest last.

    Only the LAST bar is ever in question. A provider does not hand back an
    unfinished bar from the middle of a series, and trimming on a general
    predicate would quietly drop a bar for a day the exchange was shut while the
    machine's clock said otherwise.
    """
    if not bars:
        return ()
    if session_has_settled(now, session=bars[-1].date):
        return tuple(bars)
    return tuple(bars[:-1])
