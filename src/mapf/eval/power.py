"""How large a corpus does it take to detect a real improvement?

Run **before** building the corpus, because the alternative is spending nights of
compute to produce a confidence interval spanning zero and only then asking.

Two design points drive everything here.

**The calendar is simulated, not the correlation.** Windows on different tickers
that overlap in time share market moves, and staggering dates across tickers does
not remove that — two windows five days apart still share sixteen of twenty-one
days. Rather than assume a cluster structure, this simulates daily returns for the
whole panel and sums them over the actual windows, which produces the real
dependence.

**Scoring is paired.** Both M.A.P. and the baseline see the same market move, so
when the market drops three percent both score badly and the *difference* is driven
by how the forecasts differ. Pairing removes most of the common factor, which is
why 240 forecasts is a usable sample even though the absolute scores are heavily
correlated. Residual correlation is handled by a moving-block bootstrap over
calendar time.

The reported target is the **post-cutoff holdout**: half the panel by ticker, then
roughly half again by cutoff side. Sizing on the full corpus and reporting on a
quarter of it is precisely the failure this exists to prevent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from mapf.eval.scoring import crps_normal

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class PanelDesign:
    tickers: int = 30
    dates_per_ticker: int = 8
    horizon_days: int = 21
    calendar_days: int = 504  # two years of trading days
    holdout_fraction: float = 0.5
    post_cutoff_fraction: float = 0.5

    @property
    def total_forecasts(self) -> int:
        return self.tickers * self.dates_per_ticker

    @property
    def reportable_forecasts(self) -> int:
        """What the headline number is actually computed on."""
        return int(round(self.total_forecasts * self.holdout_fraction * self.post_cutoff_fraction))


@dataclass(frozen=True)
class MarketModel:
    """Large-cap equity, roughly calibrated to what the pipeline has already seen."""

    annual_vol: float = 0.25
    market_share_of_variance: float = 0.40  # gives ~0.40 average pairwise correlation

    @property
    def daily_vol(self) -> float:
        return self.annual_vol / math.sqrt(TRADING_DAYS_PER_YEAR)

    @property
    def market_daily_vol(self) -> float:
        return self.daily_vol * math.sqrt(self.market_share_of_variance)

    @property
    def idio_daily_vol(self) -> float:
        return self.daily_vol * math.sqrt(1.0 - self.market_share_of_variance)


@dataclass(frozen=True)
class PowerResult:
    skill: float
    mean_difference: float
    baseline_crps: float
    relative_improvement: float
    power: float


def _panel_windows(
    design: PanelDesign, rng: np.random.Generator
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """Staggered start days, with within-ticker spacing of at least the horizon."""
    span = design.calendar_days - design.horizon_days
    needed = design.dates_per_ticker * design.horizon_days
    if needed > span:
        raise ValueError(
            f"{design.dates_per_ticker} non-overlapping {design.horizon_days}-day windows "
            f"need {needed} trading days but the calendar has {span}"
        )
    slack = span - needed
    ticker_ids: list[int] = []
    starts: list[int] = []
    for ticker in range(design.tickers):
        # A random offset per ticker is what staggers the panel across the calendar.
        offset = int(rng.integers(0, max(slack, 1)))
        for k in range(design.dates_per_ticker):
            ticker_ids.append(ticker)
            starts.append(offset + k * design.horizon_days)
    return np.asarray(ticker_ids, dtype=np.int64), np.asarray(starts, dtype=np.int64)


def _realised_returns(
    design: PanelDesign,
    market: MarketModel,
    ticker_ids: NDArray[np.int64],
    starts: NDArray[np.int64],
    rng: np.random.Generator,
) -> NDArray[np.float64]:
    market_daily = rng.normal(0.0, market.market_daily_vol, size=design.calendar_days)
    idio_daily = rng.normal(0.0, market.idio_daily_vol, size=(design.tickers, design.calendar_days))
    daily = idio_daily + market_daily[None, :]
    cumulative = np.concatenate([np.zeros((design.tickers, 1)), np.cumsum(daily, axis=1)], axis=1)
    ends = starts + design.horizon_days
    return np.asarray(
        cumulative[ticker_ids, ends] - cumulative[ticker_ids, starts], dtype=np.float64
    )


def _moving_block_bootstrap(
    differences: NDArray[np.float64],
    starts: NDArray[np.int64],
    rng: np.random.Generator,
    *,
    draws: int,
    block_days: int,
) -> NDArray[np.float64]:
    """Resample contiguous calendar blocks, taking every window that starts inside.

    Preserves both the cross-sectional dependence (windows open at the same time)
    and the serial dependence (windows that overlap), which resampling individual
    forecasts would destroy — and destroying it is how a confidence interval ends
    up far too narrow.
    """
    span = int(starts.max()) + 1
    n_blocks = max(1, math.ceil(span / block_days))
    order = np.argsort(starts)
    sorted_starts = starts[order]
    sorted_diffs = differences[order]

    means = np.empty(draws, dtype=np.float64)
    for draw in range(draws):
        picked: list[NDArray[np.float64]] = []
        for _ in range(n_blocks):
            begin = int(rng.integers(0, max(span - block_days, 1)))
            lo, hi = np.searchsorted(sorted_starts, (begin, begin + block_days))
            if hi > lo:
                picked.append(sorted_diffs[lo:hi])
        means[draw] = float(np.mean(np.concatenate(picked))) if picked else 0.0
    return means


def evaluate_skill(
    skill: float,
    *,
    design: PanelDesign,
    market: MarketModel,
    trials: int = 300,
    bootstrap_draws: int = 400,
    seed: int = 20260813,
) -> PowerResult:
    """Power to detect a forecaster whose mean correlates with the outcome at `skill`.

    The alternative model is deliberately modest: M.A.P. gets the volatility right
    and its central estimate has correlation `skill` with the realised return. That
    isolates directional skill, which is what a news-reading forecaster would
    plausibly have, from volatility skill, which the GARCH baseline already covers.
    """
    rng = np.random.default_rng(seed)
    sigma = market.annual_vol * math.sqrt(design.horizon_days / TRADING_DAYS_PER_YEAR)
    reportable = design.reportable_forecasts

    detections = 0
    mean_differences: list[float] = []
    baseline_scores: list[float] = []

    for _ in range(trials):
        ticker_ids, starts = _panel_windows(design, rng)
        realised = _realised_returns(design, market, ticker_ids, starts, rng)

        # Report on the post-cutoff holdout only: half the tickers, then half of
        # those windows by cutoff side.
        holdout_tickers = set(range(int(design.tickers * design.holdout_fraction)))
        mask = np.array([t in holdout_tickers for t in ticker_ids])
        mask &= (np.arange(mask.size) % 2) == 0
        realised = realised[mask][:reportable]
        window_starts = starts[mask][:reportable]

        # A forecast mean correlated with the outcome at `skill`, with the rest of
        # its variance independent — the standard construction for a fixed
        # correlation without letting the forecast see the answer.
        noise = rng.normal(0.0, sigma, size=realised.size)
        forecast_mean = skill * realised + math.sqrt(max(1.0 - skill**2, 0.0)) * noise
        forecast_mean *= skill  # a forecaster that shrinks toward zero, as it should

        map_crps = crps_normal(forecast_mean, sigma, realised)
        rw_crps = crps_normal(np.zeros_like(realised), sigma, realised)
        differences = np.asarray(map_crps - rw_crps, dtype=np.float64)

        means = _moving_block_bootstrap(
            differences,
            window_starts,
            rng,
            draws=bootstrap_draws,
            block_days=design.horizon_days * 2,
        )
        lower, upper = np.percentile(means, [2.5, 97.5])
        if upper < 0:  # M.A.P. beats the baseline, and zero is outside the interval
            detections += 1
        mean_differences.append(float(np.mean(differences)))
        baseline_scores.append(float(np.mean(rw_crps)))

    baseline = float(np.mean(baseline_scores))
    difference = float(np.mean(mean_differences))
    return PowerResult(
        skill=skill,
        mean_difference=difference,
        baseline_crps=baseline,
        relative_improvement=-difference / baseline,
        power=detections / trials,
    )
