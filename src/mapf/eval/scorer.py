"""The per-item scoring pass: forecast plus outcome plus baselines, into scores.

This is where the pieces meet. For each completed item it reads the stored
forecast, finds what actually happened, fits the three baselines on history
strictly before the window opened, and scores all four forecasters on the same
realised return.

Four decisions that are not obvious.

**M.A.P. is scored through the Monte Carlo mixture, the baselines in closed form.**
Fitting a Gaussian to the mixture and scoring that would discard the bimodality
that is the whole reason the mixture exists; the baselines genuinely are Gaussian,
so the closed form is exact rather than an approximation of them.

**The realised return is measured from the forecast's own recorded spot**, not from
whatever the price source returns today. The two should agree, and when they do not
the corpus is being scored against a different price series than the one it was
produced from — a vintage drift that ADR 0012 exists to make impossible and this
checks anyway, because "impossible" is a claim about code that can change.

**An unclosed window is refused, not skipped.** A forecast whose horizon has not
elapsed cannot be scored, and quietly dropping it would shrink the reportable
sample without saying so.

**Everything is parameterised by Protocols.** `mapf.eval` may not import
`mapf.data`, and that is what keeps this testable with generated series rather than
a live price feed.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from mapf.core.errors import MapError
from mapf.core.models import Forecast, PriceWindow
from mapf.eval.baselines import (
    BaselineError,
    History,
    Prediction,
    earnings_scaled_random_walk,
    garch,
    random_walk,
)
from mapf.eval.montecarlo import DEFAULT_PATHS, crps_against, simulate
from mapf.eval.scoring import crps_normal, pit

# Prices should match the forecast's recorded spot to the cent. A tolerance this
# loose only catches genuine drift — a different adjustment basis or vintage —
# rather than float noise.
SPOT_TOLERANCE = 1e-4

EPOCH = date(2000, 1, 1)


class ScoringError(MapError):
    """An item could not be scored."""


class WindowNotClosedError(ScoringError):
    """The forecast horizon has not elapsed yet.

    Refused rather than skipped: silently dropping unfinished windows would shrink
    the reportable sample without anything saying so.
    """


class SpotDriftError(ScoringError):
    """The price series disagrees with the spot the forecast was produced from.

    Means the corpus is being scored against different prices than it was run on —
    a retroactive adjustment or a mixed vintage (ADR 0012).
    """


@dataclass(frozen=True)
class ScoredItem:
    """One forecast, its outcome, and every forecaster's score on it."""

    ticker: str
    band: str
    as_of: date
    horizon_days: int
    realised_return: float
    day_index: int
    map_crps: float
    map_sigma: float
    map_pit: float
    baseline_crps: dict[str, float]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.baseline_crps))


def realised_return(window: PriceWindow, as_of: date, horizon_days: int, spot: float) -> float:
    """Log return over the horizon, anchored on the forecast's own spot.

    `as_of` is the last trading date the forecast saw. The horizon is counted in
    trading days, so it is an index offset in the bar series rather than a calendar
    delta — a five-day window over a long weekend is still five bars.
    """
    bars = window.bars
    index = {bar.date: i for i, bar in enumerate(bars)}
    start = index.get(as_of)
    if start is None:
        earlier = [i for i, bar in enumerate(bars) if bar.date <= as_of]
        if not earlier:
            raise ScoringError(f"no bar on or before {as_of} for {window.ticker}")
        start = max(earlier)

    opening = bars[start].close
    if abs(opening - spot) / spot > SPOT_TOLERANCE:
        raise SpotDriftError(
            f"{window.ticker} {as_of}: forecast recorded spot {spot:.4f} but the "
            f"price series now closes at {opening:.4f} — the corpus would be scored "
            f"against a different series than it was produced from"
        )

    end = start + horizon_days
    if end >= len(bars):
        raise WindowNotClosedError(
            f"{window.ticker} {as_of}: needs {horizon_days} bars after {bars[start].date}, "
            f"series has {len(bars) - start - 1}"
        )
    return math.log(bars[end].close / opening)


def score_item(
    forecast: Forecast,
    window: PriceWindow,
    *,
    band: str,
    past_earnings: Sequence[date] = (),
    paths: int = DEFAULT_PATHS,
    seed: int = 20260813,
) -> ScoredItem:
    """Score one forecast against its outcome and the three baselines.

    `window` must span both the history the baselines need and the horizon that
    followed. Baselines are fitted on bars strictly before the forecast's `as_of`,
    which is what keeps the benchmark free of the look-ahead the corpus excludes.
    """
    as_of = forecast.as_of.date()
    outcome = realised_return(window, as_of, forecast.horizon_days, forecast.spot_price)

    simulation = simulate(
        forecast.scenarios, horizon_days=forecast.horizon_days, paths=paths, seed=seed
    )
    prior = History(
        dates=tuple(bar.date for bar in window.bars),
        closes=np.array([bar.close for bar in window.bars], dtype=np.float64),
    ).before(as_of)

    baselines: dict[str, float] = {}
    for name, prediction in _fit(prior, past_earnings, forecast.horizon_days):
        baselines[name] = float(crps_normal(prediction.mean, prediction.sigma, outcome))

    return ScoredItem(
        ticker=forecast.ticker,
        band=band,
        as_of=as_of,
        horizon_days=forecast.horizon_days,
        realised_return=outcome,
        day_index=(as_of - EPOCH).days,
        map_crps=crps_against(simulation, outcome),
        map_sigma=simulation.sigma,
        map_pit=float(pit(simulation.mean, simulation.sigma, outcome)),
        baseline_crps=baselines,
    )


def _fit(
    prior: History, past_earnings: Sequence[date], horizon_days: int
) -> list[tuple[str, Prediction]]:
    """Every baseline that this history can support.

    A baseline that cannot be fitted is omitted rather than defaulted. Substituting
    a guess would put a number in the comparison column that no model produced, and
    the missing-baseline count is itself a reportable fact.
    """
    out: list[tuple[str, Prediction]] = []
    builders: tuple[tuple[str, Callable[[], Prediction]], ...] = (
        ("random_walk", lambda: random_walk(prior, horizon_days=horizon_days)),
        ("garch", lambda: garch(prior, horizon_days=horizon_days)),
        (
            "earnings_scaled_random_walk",
            lambda: earnings_scaled_random_walk(prior, past_earnings, horizon_days=horizon_days),
        ),
    )
    for name, build in builders:
        try:
            out.append((name, build()))
        except BaselineError:
            continue
    return out


@dataclass(frozen=True)
class BandScores:
    """Every scored item in a band, plus what could not be scored and why."""

    items: tuple[ScoredItem, ...]
    unscored: dict[str, int]

    @property
    def n(self) -> int:
        return len(self.items)

    def crps(self, name: str | None = None) -> list[float]:
        """M.A.P.'s scores when `name` is None, otherwise that baseline's."""
        if name is None:
            return [item.map_crps for item in self.items]
        return [item.baseline_crps[name] for item in self.items if name in item.baseline_crps]

    def paired(self, name: str) -> tuple[list[float], list[float], list[int]]:
        """M.A.P. and one baseline on exactly the items both scored.

        Pairing requires the same items on both sides; a baseline that failed on
        some of them must not be compared against M.A.P.'s scores on all of them.
        """
        both = [i for i in self.items if name in i.baseline_crps]
        return (
            [i.map_crps for i in both],
            [i.baseline_crps[name] for i in both],
            [i.day_index for i in both],
        )

    @property
    def day_index(self) -> list[int]:
        return [item.day_index for item in self.items]

    @property
    def pit_values(self) -> list[float]:
        return [item.map_pit for item in self.items]


def score_band(
    forecasts: Sequence[tuple[Forecast, str]],
    *,
    prices: Callable[[str, date, date], PriceWindow],
    earnings: Callable[[str], Sequence[date]] = lambda _: (),
    history_days: int = 730,
    paths: int = DEFAULT_PATHS,
    seed: int = 20260813,
) -> BandScores:
    """Score every forecast in a band, counting the ones that could not be.

    `prices` and `earnings` are callables rather than adapters so this module never
    imports `mapf.data` — the boundary that lets the whole pass be tested against
    generated series with no network.
    """
    from datetime import timedelta

    scored: list[ScoredItem] = []
    unscored: dict[str, int] = {}
    for forecast, band in forecasts:
        as_of = forecast.as_of.date()
        try:
            window = prices(
                forecast.ticker,
                as_of - timedelta(days=history_days),
                as_of + timedelta(days=forecast.horizon_days * 4 + 14),
            )
            scored.append(
                score_item(
                    forecast,
                    window,
                    band=band,
                    past_earnings=earnings(forecast.ticker),
                    paths=paths,
                    seed=seed,
                )
            )
        except MapError as error:
            reason = type(error).__name__
            unscored[reason] = unscored.get(reason, 0) + 1
    return BandScores(items=tuple(scored), unscored=unscored)
