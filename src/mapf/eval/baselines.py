"""Baselines: what M.A.P. has to beat.

A forecast is only meaningful against a stated alternative, so these exist before
the scorer does — there is no honest way to choose a baseline after seeing how the
system scored against it.

Each returns the same object M.A.P. produces: a mean and a dispersion for the
horizon return, so every comparison is like-for-like under CRPS.

**Every fit uses only bars strictly before the window opens.** That is not a
detail: a volatility estimated over a window that includes the forecast period is
the same look-ahead the corpus design spent its effort excluding, arriving through
the back door of the benchmark.

Three, deliberately:

- **Random walk** — zero drift, trailing realised volatility. The no-skill floor,
  and hard to beat because a drift estimated from a short history is mostly noise.
- **GARCH(1,1)** — volatility clusters, so conditioning on recent turbulence is a
  genuinely strong benchmark. A badly fitted one would flatter M.A.P., and that
  failure is invisible in the result, which is why `arch` is a dependency rather
  than fifty lines of hand-rolled MLE.
- **Earnings-multiplier** — trailing volatility scaled by a factor fit from the
  ticker's own past earnings windows. The benchmark that *widens for a scheduled
  event*, which turns the earnings confound into a measurement: losing to it means
  "fails to widen for a scheduled event a two-line heuristic handles" rather than
  the vaguer "miscalibrated" (ADR 0018).
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from numpy.typing import NDArray

from mapf.core.errors import MapError

TRADING_DAYS_PER_YEAR = 252

# A volatility estimate from a handful of bars is noise wearing a number's clothes.
MIN_BARS_FOR_VOL = 60
# GARCH needs considerably more before its parameters mean anything.
MIN_BARS_FOR_GARCH = 250


class BaselineError(MapError):
    """A baseline could not be fitted from the history available."""


@dataclass(frozen=True)
class Prediction:
    """A baseline's forecast of the horizon return, in the same units as M.A.P."""

    mean: float
    sigma: float
    name: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.sigma) or self.sigma <= 0.0:
            raise BaselineError(f"{self.name} produced a non-positive sigma: {self.sigma}")
        if not math.isfinite(self.mean):
            raise BaselineError(f"{self.name} produced a non-finite mean")


@dataclass(frozen=True)
class History:
    """Daily closes strictly before the forecast opens.

    `dates` and `closes` are parallel and ascending. Holding the dates rather than
    an anonymous array is what lets the earnings baseline line its windows up with
    filing dates without a second lookup.
    """

    dates: tuple[date, ...]
    closes: NDArray[np.float64]

    def __post_init__(self) -> None:
        if len(self.dates) != self.closes.size:
            raise BaselineError("history dates and closes are different lengths")
        if self.closes.size and float(np.min(self.closes)) <= 0.0:
            raise BaselineError("history contains a non-positive close")

    @property
    def log_returns(self) -> NDArray[np.float64]:
        return np.diff(np.log(self.closes))

    def before(self, cutoff: date) -> History:
        """The strictly-earlier prefix. The guard against look-ahead lives here."""
        keep = sum(1 for d in self.dates if d < cutoff)
        return History(dates=self.dates[:keep], closes=self.closes[:keep])


def _require(history: History, minimum: int, name: str) -> NDArray[np.float64]:
    returns = history.log_returns
    if returns.size < minimum:
        raise BaselineError(
            f"{name} needs {minimum} returns, history has {returns.size}"
        )
    return returns


def random_walk(history: History, *, horizon_days: int) -> Prediction:
    """Zero drift, trailing realised volatility scaled to the horizon.

    The drift is set to zero rather than estimated. A mean return fitted from a
    year of daily data has a standard error of roughly the volatility itself, so
    estimating it adds variance and no signal — and a baseline that beats itself by
    accident is worse than none.
    """
    returns = _require(history, MIN_BARS_FOR_VOL, "random_walk")
    daily = float(np.std(returns, ddof=1))
    return Prediction(
        mean=0.0, sigma=daily * math.sqrt(horizon_days), name="random_walk"
    )


def garch(history: History, *, horizon_days: int) -> Prediction:
    """GARCH(1,1) on daily log returns, forecast out to the horizon.

    Fitted on percentage returns because `arch` optimises far more reliably at that
    scale; the result is converted back. The variance forecast is summed over the
    horizon rather than scaled by root-time, since GARCH's whole content is that
    tomorrow's variance is not today's.
    """
    from arch import arch_model  # imported lazily: fitting is slow to import

    returns = _require(history, MIN_BARS_FOR_GARCH, "garch")
    scaled = returns * 100.0
    with warnings.catch_warnings():
        # Convergence chatter on well-behaved series is noise; a genuine failure
        # surfaces as a non-finite forecast below.
        warnings.simplefilter("ignore")
        model = arch_model(scaled, vol="GARCH", p=1, q=1, mean="Zero", rescale=False)
        fitted = model.fit(disp="off", show_warning=False)
        forecast = fitted.forecast(horizon=horizon_days, reindex=False)
    variances = np.asarray(forecast.variance.to_numpy(), dtype=np.float64).ravel()
    if variances.size < horizon_days or not np.all(np.isfinite(variances)):
        raise BaselineError("garch produced a non-finite variance forecast")
    total = float(np.sum(variances[:horizon_days])) / (100.0**2)
    return Prediction(mean=0.0, sigma=math.sqrt(total), name="garch")


def earnings_multiplier(
    history: History, past_earnings: Sequence[date], *, horizon_days: int
) -> float:
    """Ratio of realised dispersion in past earnings windows to ordinary windows.

    Fitted per ticker on that ticker's own history, strictly before the forecast.
    Returns 1.0 when there is not enough evidence — a neutral multiplier is honest
    about knowing nothing, whereas a global constant would smuggle in an average of
    other companies.
    """
    returns = _require(history, MIN_BARS_FOR_VOL, "earnings_multiplier")
    index = {day: i for i, day in enumerate(history.dates)}
    starts = sorted({index[d] for d in past_earnings if d in index})

    earnings: list[float] = []
    ordinary: list[float] = []
    windows = dict.fromkeys(starts, True)
    for i in range(returns.size - horizon_days):
        window = float(np.sum(returns[i : i + horizon_days]))
        (earnings if i in windows else ordinary).append(window)

    if len(earnings) < 2 or len(ordinary) < MIN_BARS_FOR_VOL:
        return 1.0
    wide = float(np.std(earnings, ddof=1))
    calm = float(np.std(ordinary, ddof=1))
    if calm <= 0.0 or not math.isfinite(wide / calm):
        return 1.0
    return wide / calm


def earnings_scaled_random_walk(
    history: History, past_earnings: Sequence[date], *, horizon_days: int
) -> Prediction:
    """Trailing volatility widened by the ticker's own earnings multiplier.

    The benchmark that *does* widen for a scheduled event. If M.A.P. loses to this,
    the finding is specific and useful: it fails to widen for something a two-line
    heuristic handles.
    """
    base = random_walk(history, horizon_days=horizon_days)
    factor = earnings_multiplier(history, past_earnings, horizon_days=horizon_days)
    return Prediction(
        mean=0.0, sigma=base.sigma * factor, name="earnings_scaled_random_walk"
    )
