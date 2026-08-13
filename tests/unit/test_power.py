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
    evaluate_calibration,
    evaluate_skill,
    ex_dividend_window_probability,
    max_non_overlapping_dates,
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
        # 60 windows of 5 days need 300 trading days; 252 leaves 247 usable.
        _panel_windows(
            PanelDesign(dates_per_ticker=60, calendar_days=252), np.random.default_rng(0)
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


# ---------------------------------------------------------------------------
# Calibration power, and the horizon decision
# ---------------------------------------------------------------------------
def test_perfect_calibration_is_not_flagged() -> None:
    """Two-sided test, correctly sized. A forecaster with the right dispersion must
    not be declared miscalibrated, or every reported calibration failure is noise."""
    result = evaluate_calibration(
        1.0, design=PanelDesign(), market=MarketModel(), trials=40, bootstrap_draws=150
    )
    assert result.power <= 0.10


def test_a_grossly_overconfident_forecaster_is_always_caught() -> None:
    """The first live run's actual failure: vol 0.05 against a realised 0.25."""
    result = evaluate_calibration(
        0.2, design=PanelDesign(), market=MarketModel(), trials=40, bootstrap_draws=150
    )
    assert result.power >= 0.95


def test_calibration_is_far_more_detectable_than_direction() -> None:
    """The finding ADR 0015 rests on, asserted so it cannot silently stop being true."""
    design, market = PanelDesign(), MarketModel()
    calibration = evaluate_calibration(
        0.5, design=design, market=market, trials=40, bootstrap_draws=150
    )
    direction = evaluate_skill(0.20, design=design, market=market, trials=40, bootstrap_draws=150)
    assert calibration.power > 2 * direction.power


def test_the_panel_default_horizon_is_five_days() -> None:
    """Frozen by ADR 0016. Pinned so a later edit has to be deliberate."""
    assert PanelDesign().horizon_days == 5


def test_a_shorter_horizon_frees_the_calendar() -> None:
    assert max_non_overlapping_dates(5, 504) > 4 * max_non_overlapping_dates(21, 504)


def test_a_third_of_21_day_windows_are_dividend_contaminated() -> None:
    """The measured argument for the 5-day horizon: ADR 0013 excludes these, so the
    longer window quietly costs a third of the reportable sample."""
    assert ex_dividend_window_probability(21) == pytest.approx(0.333, abs=0.01)
    assert ex_dividend_window_probability(5) == pytest.approx(0.079, abs=0.01)
