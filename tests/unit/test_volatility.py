"""The trailing realised volatility that experiment A2 shows the analyst (ADR 0042).

Offline and numeric. The property that matters is that it IS the random-walk baseline's
volatility, which lives on the other side of the `eval` boundary the pipeline may not
cross: this file is what holds the two estimators together.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pytest

from mapf.core.errors import InsufficientVolatilityHistoryError, MarketDataError
from mapf.core.volatility import MIN_RETURNS, TRADING_DAYS_PER_YEAR, trailing_annualised_vol
from mapf.eval.baselines import MIN_BARS_FOR_VOL, History, random_walk
from mapf.eval.baselines import TRADING_DAYS_PER_YEAR as BASELINE_DAYS

TICKER = "AAPL"
FIRST_DAY = date(2026, 1, 1)


def _closes(count: int = 140) -> list[float]:
    """A deterministic series that actually moves."""
    closes = [100.0]
    for index in range(1, count):
        closes.append(closes[-1] * math.exp(0.012 * math.sin(1.3 * index) + 0.003))
    return closes


def _by_hand(closes: list[float]) -> float:
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:], strict=False)]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(252)


def test_it_is_the_sample_sd_of_daily_log_returns_annualised() -> None:
    closes = _closes(100)
    assert trailing_annualised_vol(closes, ticker=TICKER) == pytest.approx(_by_hand(closes))


def test_it_is_the_random_walk_baselines_own_volatility() -> None:
    """The comparison of A2 against that baseline is interpretable only if the two
    are one estimator. They live in different packages, so this is what holds them."""
    closes = _closes(200)
    history = History(
        dates=tuple(FIRST_DAY + timedelta(days=index) for index in range(len(closes))),
        closes=np.array(closes, dtype=float),
    )
    daily_times_root_one = random_walk(history, horizon_days=1).sigma
    assert trailing_annualised_vol(closes, ticker=TICKER) == pytest.approx(
        daily_times_root_one * math.sqrt(TRADING_DAYS_PER_YEAR)
    )
    assert (MIN_RETURNS, TRADING_DAYS_PER_YEAR) == (MIN_BARS_FOR_VOL, BASELINE_DAYS)


def test_sixty_returns_is_enough_and_fifty_nine_is_not() -> None:
    assert trailing_annualised_vol(_closes(MIN_RETURNS + 1), ticker=TICKER) > 0.0
    with pytest.raises(InsufficientVolatilityHistoryError) as caught:
        trailing_annualised_vol(_closes(MIN_RETURNS), ticker=TICKER)
    assert (caught.value.returns, caught.value.minimum) == (MIN_RETURNS - 1, MIN_RETURNS)
    assert "59 daily returns" in str(caught.value)


def test_a_series_that_does_not_move_is_not_a_volatility_of_zero() -> None:
    with pytest.raises(InsufficientVolatilityHistoryError, match="do not move"):
        trailing_annualised_vol([50.0] * 80, ticker=TICKER)


@pytest.mark.parametrize("bad", [0.0, -3.0, math.nan, math.inf])
def test_a_close_that_cannot_be_a_price_is_refused(bad: float) -> None:
    closes = _closes(80)
    closes[10] = bad
    with pytest.raises(MarketDataError, match="non-positive or non-finite"):
        trailing_annualised_vol(closes, ticker=TICKER)
