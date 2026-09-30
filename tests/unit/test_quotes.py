"""The latest trade, whether the market is open, and when a page should ask again.

For the local app's company page only (ADR 0039). Nothing here reaches a run: a
quote is not a close, and the port it comes through is not the one a forecast
reads. No network: the one-minute frames are built here.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from mapf.core.errors import EmptyPriceWindowError, MarketDataUnavailableError
from mapf.core.sessions import (
    REFRESH_OPEN_S,
    REFRESH_UNSURE_S,
    market_state,
    next_open,
    seconds_until_next_check,
)
from mapf.data.providers.yfinance_provider import YFinanceQuotes

NY = ZoneInfo("America/New_York")


def _minutes(stamps: list[pd.Timestamp], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"Close": closes}, index=pd.DatetimeIndex(stamps))


# --- the quote -------------------------------------------------------------------


def test_the_quote_is_the_last_minutes_close_and_its_time_in_utc() -> None:
    stamps = [pd.Timestamp("2026-09-30 14:30", tz=NY), pd.Timestamp("2026-09-30 14:31", tz=NY)]
    quotes = YFinanceQuotes(minutes=lambda _t: _minutes(stamps, [70.10, 70.12]))
    latest = quotes.latest("KO")
    assert latest.price == 70.12
    assert latest.at == datetime(2026, 9, 30, 18, 31, tzinfo=UTC)
    assert latest.provider == quotes.name == "yfinance"


def test_a_bare_stamp_is_read_on_the_exchanges_clock_not_this_machines() -> None:
    stamps = [pd.Timestamp("2026-09-30 15:59")]
    latest = YFinanceQuotes(minutes=lambda _t: _minutes(stamps, [70.0])).latest("KO")
    assert latest.at == datetime(2026, 9, 30, 19, 59, tzinfo=UTC)


def test_a_minute_without_a_close_is_skipped_for_the_last_one_that_has_one() -> None:
    stamps = [pd.Timestamp("2026-09-30 14:30", tz=NY), pd.Timestamp("2026-09-30 14:31", tz=NY)]
    latest = YFinanceQuotes(minutes=lambda _t: _minutes(stamps, [70.1, float("nan")])).latest("KO")
    assert latest.price == 70.1


def test_no_quote_is_an_error_that_says_so_never_a_zero() -> None:
    empty = YFinanceQuotes(minutes=lambda _t: pd.DataFrame({"Close": []}))
    with pytest.raises(EmptyPriceWindowError):
        empty.latest("KO")
    blank = YFinanceQuotes(
        minutes=lambda _t: _minutes([pd.Timestamp("2026-09-30 14:30", tz=NY)], [float("nan")])
    )
    with pytest.raises(EmptyPriceWindowError):
        blank.latest("KO")

    def broken(_t: str) -> pd.DataFrame:
        raise KeyError("chart")

    with pytest.raises(MarketDataUnavailableError, match="KeyError"):
        YFinanceQuotes(minutes=broken).latest("KO")


def test_the_app_builds_one_source_of_quotes() -> None:
    from mapf.bootstrap import build_quotes

    assert build_quotes().name == "yfinance"


# --- open or closed ---------------------------------------------------------------


def _ny(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=NY)


def test_open_needs_the_hours_and_a_trade_today() -> None:
    now = _ny(2026, 9, 30, 14, 32)  # a Wednesday
    assert market_state(now, last_trade=_ny(2026, 9, 30, 14, 31)) == "open"


def test_a_weekday_in_hours_with_no_trade_today_is_closed_which_is_what_a_holiday_is() -> None:
    now = _ny(2026, 11, 26, 11, 0)  # Thanksgiving: the clock says open, nothing traded
    assert market_state(now, last_trade=_ny(2026, 11, 25, 15, 59)) == "closed"
    assert market_state(now, last_trade=None) == "closed"


def test_outside_hours_it_is_closed_whatever_traded() -> None:
    assert market_state(_ny(2026, 9, 30, 16, 5), last_trade=_ny(2026, 9, 30, 15, 59)) == "closed"
    assert market_state(_ny(2026, 9, 30, 9, 29), last_trade=_ny(2026, 9, 30, 9, 29)) == "closed"
    assert market_state(_ny(2026, 10, 3, 12, 0), last_trade=_ny(2026, 10, 3, 12, 0)) == "closed"


def test_a_clock_without_a_zone_is_refused() -> None:
    with pytest.raises(ValueError, match="aware"):
        market_state(datetime(2026, 9, 30, 14, 0), last_trade=None)  # noqa: DTZ001


def test_the_next_opening_bell_skips_the_weekend() -> None:
    assert next_open(_ny(2026, 10, 2, 17, 0)) == _ny(2026, 10, 5, 9, 30)  # Friday → Monday
    assert next_open(_ny(2026, 9, 30, 8, 0)) == _ny(2026, 9, 30, 9, 30)
    assert next_open(_ny(2026, 9, 30, 9, 30)) == _ny(2026, 10, 1, 9, 30), "strictly after"
    assert next_open(datetime(2026, 10, 3, 12, 0, tzinfo=UTC)) == _ny(2026, 10, 5, 9, 30)


def test_a_page_asks_every_minute_while_open_and_at_the_next_bell_while_shut() -> None:
    assert seconds_until_next_check(_ny(2026, 9, 30, 14, 32), "open") == REFRESH_OPEN_S
    assert seconds_until_next_check(_ny(2026, 11, 26, 11, 0), "closed") == REFRESH_UNSURE_S
    evening = _ny(2026, 9, 30, 20, 0)
    assert seconds_until_next_check(evening, "closed") == int(
        (_ny(2026, 10, 1, 9, 30) - evening).total_seconds()
    )
    almost = _ny(2026, 10, 1, 9, 29, 30)
    assert seconds_until_next_check(almost, "closed") == REFRESH_OPEN_S, "never under a minute"


# --- the page's two-year window ----------------------------------------------------


def test_the_window_is_the_same_date_two_years_back_and_leap_days_fall_to_the_28th() -> None:
    from mapf.cli.commands.serve import years_before

    assert years_before(date(2026, 9, 30), 2) == date(2024, 9, 30)
    assert years_before(date(2026, 10, 1), 2) == date(2024, 10, 1)
    assert years_before(date(2028, 2, 29), 2) == date(2026, 2, 28)
    assert date(2026, 9, 30) - years_before(date(2026, 9, 30), 2) == timedelta(days=730)
