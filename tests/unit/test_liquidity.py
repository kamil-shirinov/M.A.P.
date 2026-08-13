"""The liquidity screen.

The screen decides what asset class the corpus is drawn from, so the assertions
here are about the ways a bad candidate could look like a good one: a thin name
carried over the floor by one busy day, and a name with a healthy median computed
from a handful of bars.
"""

from __future__ import annotations

from datetime import date

from mapf.core.errors import EmptyPriceWindowError, MarketDataUnavailableError, PromptError
from mapf.core.models import Bar, PriceWindow
from mapf.data.liquidity import MarketLiquidity

START, END = date(2024, 1, 1), date(2024, 12, 31)


def _window(volumes: list[float], close: float = 100.0) -> PriceWindow:
    return PriceWindow(
        ticker="TEST",
        provider="fake",
        adjustment="split_adjusted",
        bars=tuple(
            Bar(
                date=date(2024, 1, 1) + __import__("datetime").timedelta(days=i),
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=int(v),
            )
            for i, v in enumerate(volumes)
        ),
    )


class FakeMarket:
    def __init__(self, window: PriceWindow | None = None, error: Exception | None = None) -> None:
        self.window = window
        self.error = error

    @property
    def name(self) -> str:
        return "fake"

    def get_ohlcv(self, ticker: str, start: date, end: date) -> PriceWindow:
        if self.error is not None:
            raise self.error
        assert self.window is not None
        return self.window


def test_median_dollar_volume_is_close_times_volume() -> None:
    market = FakeMarket(_window([1_000.0] * 250, close=50.0))
    screen = MarketLiquidity(market)
    assert screen.median_dollar_volume("TEST", START, END) == 50_000.0


def test_one_busy_day_does_not_carry_a_thin_name_over_the_floor() -> None:
    """The mean would. That is the whole reason this is a median."""
    volumes = [1_000.0] * 249 + [10_000_000_000.0]
    screen = MarketLiquidity(FakeMarket(_window(volumes, close=10.0)))
    assert screen.median_dollar_volume("TEST", START, END) == 10_000.0


def test_too_few_bars_is_treated_as_no_history() -> None:
    """A name that traded 20 days was suspended, listed late, or delisted. Its
    median can look perfectly healthy."""
    screen = MarketLiquidity(FakeMarket(_window([1_000_000.0] * 20, close=500.0)))
    assert screen.median_dollar_volume("TEST", START, END) is None


def test_exactly_the_minimum_number_of_bars_is_accepted() -> None:
    screen = MarketLiquidity(FakeMarket(_window([1_000.0] * 200, close=10.0)))
    assert screen.median_dollar_volume("TEST", START, END) == 10_000.0


def test_an_unavailable_ticker_screens_as_none_rather_than_raising() -> None:
    """Absent history is a screening answer, not a run failure."""
    screen = MarketLiquidity(FakeMarket(error=MarketDataUnavailableError("fake", "gone")))
    assert screen.median_dollar_volume("NOPE", START, END) is None


def test_an_empty_window_screens_as_none() -> None:
    screen = MarketLiquidity(FakeMarket(error=EmptyPriceWindowError("fake", "NOPE")))
    assert screen.median_dollar_volume("NOPE", START, END) is None


def test_an_unexpected_map_error_screens_as_none_and_warns() -> None:
    """One broken candidate must not end a walk over thousands of them."""
    screen = MarketLiquidity(FakeMarket(error=PromptError("unexpected")))
    assert screen.median_dollar_volume("NOPE", START, END) is None


def test_the_minimum_bar_count_is_configurable() -> None:
    screen = MarketLiquidity(FakeMarket(_window([5.0] * 10, close=2.0)), min_bars=5)
    assert screen.median_dollar_volume("TEST", START, END) == 10.0
