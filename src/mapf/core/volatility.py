"""A stock's own trailing realised volatility, computed once and the same way twice.

The random-walk baseline scores a forecast against exactly this quantity: the sample
standard deviation of daily log returns over the closes it is given, scaled to the
horizon. Experiment A2 hands the analyst the same number (ADR 0042), and the
comparison of A2 against that baseline is only interpretable if the two are the same
estimator. They are written here separately from `mapf.eval.baselines` because the
pipeline cannot import `eval`: `eval` is excluded from the forecast digest on the
grounds that nothing a forecast depends on imports it (ADR 0026). A test pins the two
to each other so they cannot drift.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from mapf.core.errors import InsufficientVolatilityHistoryError, MarketDataError

TRADING_DAYS_PER_YEAR = 252
# A volatility from a handful of bars is noise wearing a number's clothes. Equal to
# the baseline's own floor, so an item the baseline could not fit is not one this
# could.
MIN_RETURNS = 60


def trailing_annualised_vol(closes: Sequence[float], *, ticker: str) -> float:
    """Sample SD of daily log returns (ddof=1), times the root of 252.

    Annualised because the forecast's own `vol` field is: the number the analyst is
    asked to write and the number it is shown share one scale, so no conversion sits
    between them for the model to get wrong.

    `closes` must be strictly before the session the forecast opens from, which is
    the caller's to arrange and the reason this takes no dates: it has nothing to
    check them against.
    """
    if any(not math.isfinite(close) or close <= 0.0 for close in closes):
        raise MarketDataError(f"{ticker}: the closes hold a non-positive or non-finite value")
    returns = [math.log(b / a) for a, b in zip(closes, closes[1:], strict=False)]
    if len(returns) < MIN_RETURNS:
        raise InsufficientVolatilityHistoryError(ticker, len(returns), MIN_RETURNS)
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    if variance <= 0.0:
        raise InsufficientVolatilityHistoryError(ticker, len(returns), MIN_RETURNS, flat=True)
    return math.sqrt(variance) * math.sqrt(TRADING_DAYS_PER_YEAR)
