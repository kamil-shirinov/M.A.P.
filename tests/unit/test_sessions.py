"""A bar for a session still in progress is not a close.

The defect this exists for: a live run at 15:52 ET anchored at 87.33, eight
minutes before the bell. The settled close for that same session was 87.18. Every
artifact around it — the manifest's `last_trading_date`, the forecast's
`spot_price`, the screen's "at that day's close" — said close, and none of them
was wrong about anything except the thing that mattered.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from mapf.core.sessions import EXCHANGE_TZ, session_has_settled, settled, settled_since

SESSION = date(2026, 9, 28)


class _Bar:
    def __init__(self, day: date, close: float = 1.0) -> None:
        self.date = day
        self.close = close


def _et(hour: int, minute: int = 0, day: date = SESSION) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=EXCHANGE_TZ)


# --- the rule ------------------------------------------------------------------


def test_a_session_is_open_until_the_bell() -> None:
    assert session_has_settled(_et(9, 30), session=SESSION) is False
    assert session_has_settled(_et(15, 52), session=SESSION) is False
    assert session_has_settled(_et(15, 59), session=SESSION) is False


def test_the_bell_is_not_the_close() -> None:
    """Trading ends at 16:00; the official close comes out of the closing auction
    and can reach a provider minutes later. A bar read at 16:10 can still move."""
    assert session_has_settled(_et(16, 0), session=SESSION) is False
    assert session_has_settled(_et(16, 10), session=SESSION) is False
    assert session_has_settled(_et(16, 29), session=SESSION) is False


def test_it_has_settled_from_half_past_four() -> None:
    assert session_has_settled(_et(16, 30), session=SESSION) is True
    assert session_has_settled(_et(20, 0), session=SESSION) is True


def test_an_earlier_day_has_not_closed_and_a_later_one_has() -> None:
    """Both directions matter. A bar dated tomorrow is not settled because
    tomorrow has not happened; a bar dated yesterday is."""
    assert session_has_settled(_et(12, 0), session=date(2026, 9, 29)) is False
    assert session_has_settled(_et(12, 0), session=date(2026, 9, 25)) is True


def test_the_boundary_is_read_in_new_york_not_locally() -> None:
    """15:52 ET is 19:52 UTC and 20:52 in London. Judged on a local clock, the
    same instant is 'after four o'clock' in two of those three places."""
    instant = datetime(2026, 9, 28, 19, 52, tzinfo=UTC)
    assert session_has_settled(instant, session=SESSION) is False
    # 20:31 UTC is 16:31 in New York in September: settled.
    assert session_has_settled(datetime(2026, 9, 28, 20, 31, tzinfo=UTC), session=SESSION) is True


def test_daylight_saving_moves_the_boundary_in_utc() -> None:
    """16:30 in New York is 20:30 UTC in October and 21:30 UTC in December. A
    fixed offset would be wrong for five months and would fail in a way that only
    shows twice a year."""
    october = date(2026, 10, 15)
    december = date(2026, 12, 15)
    assert session_has_settled(datetime(2026, 10, 15, 20, 31, tzinfo=UTC), session=october) is True
    assert (
        session_has_settled(datetime(2026, 12, 15, 20, 31, tzinfo=UTC), session=december) is False
    )
    assert session_has_settled(datetime(2026, 12, 15, 21, 31, tzinfo=UTC), session=december) is True


def test_a_naive_datetime_is_refused_rather_than_guessed() -> None:
    """Reading it in the machine's own zone is the bug this module removes, not a
    convenience it should offer."""
    with pytest.raises(ValueError, match="aware datetime"):
        session_has_settled(datetime(2026, 9, 28, 15, 52), session=SESSION)


# --- trimming ------------------------------------------------------------------


def test_the_unfinished_bar_is_dropped_mid_session() -> None:
    bars = [_Bar(date(2026, 9, 25), 87.0), _Bar(SESSION, 87.33)]
    kept = settled(bars, now=_et(15, 52))
    assert [b.date for b in kept] == [date(2026, 9, 25)]
    assert kept[-1].close == 87.0


def test_it_is_kept_once_the_session_has_settled() -> None:
    bars = [_Bar(date(2026, 9, 25), 87.0), _Bar(SESSION, 87.18)]
    kept = settled(bars, now=_et(16, 30))
    assert [b.date for b in kept] == [date(2026, 9, 25), SESSION]
    assert kept[-1].close == 87.18


def test_a_run_the_next_morning_keeps_the_whole_series() -> None:
    """The second live run was made at 04:48 ET the following day, and correctly
    anchored on the settled 87.18."""
    bars = [_Bar(date(2026, 9, 25)), _Bar(SESSION)]
    assert len(settled(bars, now=_et(4, 48, day=date(2026, 9, 29)))) == 2


def test_only_the_last_bar_is_ever_in_question() -> None:
    """A provider does not hand back an unfinished bar from the middle. Trimming
    on a general predicate would drop bars for days the exchange was shut."""
    bars = [_Bar(date(2026, 9, 24)), _Bar(date(2026, 9, 25)), _Bar(SESSION)]
    kept = settled(bars, now=_et(10, 0))
    assert [b.date for b in kept] == [date(2026, 9, 24), date(2026, 9, 25)]


def test_an_empty_series_stays_empty() -> None:
    assert settled([], now=_et(10, 0)) == ()


def test_a_single_unfinished_bar_leaves_nothing() -> None:
    """Which the run path turns into a refusal rather than anchoring on nothing."""
    assert settled([_Bar(SESSION)], now=_et(10, 0)) == ()


# --- a settle between a fetch and a read (ADR 0040) -----------------------------


def _utc(hour: int, minute: int = 0, day: date = SESSION) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def test_a_fetch_before_the_settle_and_a_read_after_it_names_that_day() -> None:
    # 28 Sep 2026 is in daylight time: 16:30 in New York is 20:30 UTC.
    assert settled_since(_et(8), now=_et(17)) == SESSION
    assert settled_since(_utc(14), now=_utc(20, 31)) == SESSION


def test_the_settle_instant_itself_counts_as_passed() -> None:
    assert settled_since(_et(16, 29), now=_et(16, 30)) == SESSION


def test_a_read_before_the_settle_has_nothing_to_refresh() -> None:
    assert settled_since(_et(8), now=_et(16, 29)) is None


def test_a_fetch_at_or_after_the_settle_is_already_settled() -> None:
    """The refetch happens once: after it the file's own instant is past the settle."""
    assert settled_since(_et(16, 30), now=_et(17)) is None
    assert settled_since(_et(16, 45), now=_et(23, 59)) is None


def test_the_settle_follows_new_yorks_clock_through_the_winter_change() -> None:
    """Standard time: 16:30 is 21:30 UTC, an hour later than in September. A fixed
    20:30 UTC would call a 21:00 UTC read settled and refetch a window still open."""
    winter = date(2026, 12, 2)
    assert settled_since(_utc(15, day=winter), now=_utc(21, 0, day=winter)) is None
    assert settled_since(_utc(15, day=winter), now=_utc(21, 30, day=winter)) == winter


def test_only_the_reads_own_new_york_day_is_asked_about() -> None:
    """00:30 UTC on the 29th is still 20:30 on the 28th in New York."""
    assert settled_since(_utc(14), now=_utc(0, 30, day=date(2026, 9, 29))) == SESSION


def test_a_naive_instant_is_refused() -> None:
    with pytest.raises(ValueError, match="aware"):
        settled_since(datetime(2026, 9, 28, 8, 0), now=_et(17))
    with pytest.raises(ValueError, match="aware"):
        settled_since(_et(8), now=datetime(2026, 9, 28, 17, 0))
