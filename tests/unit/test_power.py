"""The power analysis, tested for the properties that make it trustworthy.

A power analysis that is itself wrong is worse than none: it produces a number
that licenses spending nights of compute. The assertions here are about the
simulation's structure, not about any particular power figure.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from mapf.eval.power import (
    TRADING_DAYS_PER_YEAR,
    MarketModel,
    PanelDesign,
    _panel_windows,
    _realised_returns,
    evaluate_skill,
)


def test_the_reportable_sample_is_a_quarter_of_the_corpus() -> None:
    """The number that matters is not the corpus size. Halving by ticker for the
    holdout and again by cutoff side leaves a quarter, and sizing on the whole is
    the failure this analysis exists to prevent."""
    design = PanelDesign(tickers=30, dates_per_ticker=8)
    assert design.total_forecasts == 240
    assert design.reportable_forecasts == 60


def test_within_ticker_windows_never_overlap() -> None:
    """The independence the panel design is built on. If consecutive dates for one
    ticker were closer than the horizon, the windows would share days and the
    sample would be smaller than it looks."""
    design = PanelDesign(tickers=5, dates_per_ticker=6)
    rng = np.random.default_rng(0)
    tickers, starts = _panel_windows(design, rng)
    for ticker in set(tickers.tolist()):
        own = np.sort(starts[tickers == ticker])
        assert np.all(np.diff(own) >= design.horizon_days)


def test_a_calendar_too_short_for_the_panel_is_rejected() -> None:
    with pytest.raises(ValueError, match="need"):
        _panel_windows(
            PanelDesign(dates_per_ticker=40, calendar_days=252), np.random.default_rng(0)
        )


def test_realised_returns_have_the_intended_volatility() -> None:
    """If the simulated market is not calibrated, every power number is fiction."""
    design = PanelDesign(tickers=200, dates_per_ticker=8)
    market = MarketModel(annual_vol=0.25)
    rng = np.random.default_rng(7)
    tickers, starts = _panel_windows(design, rng)
    returns = _realised_returns(design, market, tickers, starts, rng)
    expected = 0.25 * math.sqrt(design.horizon_days / TRADING_DAYS_PER_YEAR)
    assert float(np.std(returns)) == pytest.approx(expected, rel=0.1)


def test_windows_open_at_the_same_time_are_correlated() -> None:
    """The reason the bootstrap resamples calendar blocks. Staggering dates across
    tickers does not remove this — two windows five days apart still share sixteen
    of twenty-one days."""
    design = PanelDesign(tickers=2, dates_per_ticker=1, calendar_days=504)
    market = MarketModel(market_share_of_variance=0.9)
    rng = np.random.default_rng(3)
    pairs = []
    for _ in range(400):
        tickers = np.array([0, 1])
        starts = np.array([100, 100])  # identical windows
        pairs.append(_realised_returns(design, market, tickers, starts, rng))
    both = np.array(pairs)
    assert float(np.corrcoef(both[:, 0], both[:, 1])[0, 1]) > 0.8


def test_no_skill_gives_no_detection() -> None:
    """The test must be correctly sized: a forecaster with zero skill must not be
    declared better than the baseline. A power analysis with an inflated false
    positive rate would recommend a corpus that finds skill in noise."""
    result = evaluate_skill(
        0.0, design=PanelDesign(), market=MarketModel(), trials=40, bootstrap_draws=150
    )
    assert result.power <= 0.10
    assert result.mean_difference == pytest.approx(0.0, abs=1e-4)


def test_more_skill_is_more_detectable() -> None:
    """Monotonicity. Without it the simulation is not measuring skill at all."""
    weak = evaluate_skill(
        0.10, design=PanelDesign(), market=MarketModel(), trials=40, bootstrap_draws=150
    )
    strong = evaluate_skill(
        0.40, design=PanelDesign(), market=MarketModel(), trials=40, bootstrap_draws=150
    )
    assert strong.power > weak.power
    assert strong.relative_improvement > weak.relative_improvement
