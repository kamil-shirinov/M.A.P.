"""A forecast must not anchor on a session that has not closed.

The run this caught was made at 15:52 in New York, eight minutes before the bell.
Its anchor was 87.33; the settled close for the same session was 87.18. Nothing
in the artifacts was wrong except the one thing that mattered — every field said
"close", and the provider's bar for the day in progress looks exactly like one.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from mapf.core.errors import MarketDataError
from mapf.core.models import Bar, PriceWindow
from mapf.pipeline.run import settled_window


def _bar(day: date, close: float) -> Bar:
    return Bar(date=day, open=close, high=close, low=close, close=close, volume=1_000_000)


def _window(*bars: Bar) -> PriceWindow:
    return PriceWindow(
        ticker="KO",
        provider="yfinance",
        adjustment="split_adjusted",
        bars=tuple(bars),
    )


MID_SESSION = datetime(2026, 9, 28, 19, 52, tzinfo=UTC)  # 15:52 in New York
AFTER_CLOSE = datetime(2026, 9, 28, 20, 30, tzinfo=UTC)  # 16:30 in New York


def test_the_unfinished_bar_is_dropped_and_the_anchor_moves_back() -> None:
    window = _window(_bar(date(2026, 9, 25), 87.18), _bar(date(2026, 9, 28), 87.33))

    trimmed = settled_window(window, as_of=MID_SESSION)

    assert trimmed.last_trading_date == date(2026, 9, 25)
    assert trimmed.last_close == 87.18
    # The live quote is gone rather than relabelled.
    assert all(b.date != date(2026, 9, 28) for b in trimmed.bars)


def test_after_the_bell_the_session_is_kept() -> None:
    window = _window(_bar(date(2026, 9, 25), 87.0), _bar(date(2026, 9, 28), 87.18))

    trimmed = settled_window(window, as_of=AFTER_CLOSE)

    assert trimmed.last_trading_date == date(2026, 9, 28)
    assert trimmed.last_close == 87.18


def test_a_window_of_nothing_but_an_unfinished_session_refuses() -> None:
    """Anchoring on it would produce a forecast whose `spot_price` is a live quote
    labelled as a close, which is the defect this whole path exists to remove."""
    window = _window(_bar(date(2026, 9, 28), 87.33))

    with pytest.raises(MarketDataError, match="has not closed yet"):
        settled_window(window, as_of=MID_SESSION)


def test_the_refusal_names_the_ticker_and_the_day() -> None:
    window = _window(_bar(date(2026, 9, 28), 87.33))

    with pytest.raises(MarketDataError) as caught:
        settled_window(window, as_of=MID_SESSION)

    assert "KO" in str(caught.value)
    assert "2026-09-28" in str(caught.value)


def test_a_historical_window_is_untouched() -> None:
    """Every corpus run is anchored in the past, so this path must be a no-op for
    all 701 of them."""
    window = _window(_bar(date(2025, 5, 1), 60.0), _bar(date(2025, 5, 2), 61.0))

    trimmed = settled_window(window, as_of=datetime(2026, 9, 28, 12, 0, tzinfo=UTC))

    assert trimmed.bars == window.bars
