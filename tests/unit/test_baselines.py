"""The baselines M.A.P. is measured against.

A baseline that is quietly wrong flatters the system it benchmarks, and that
failure is invisible in the final number — so these are tested against
known answers and against the specific ways each one could cheat.

No network and no inference: every series here is generated.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pytest

from mapf.eval.baselines import (
    TRADING_DAYS_PER_YEAR,
    BaselineError,
    History,
    Prediction,
    earnings_multiplier,
    earnings_scaled_random_walk,
    garch,
    random_walk,
)

HORIZON = 5


def _history(returns: np.ndarray, start: date = date(2024, 1, 1)) -> History:
    closes = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(returns)]))
    days = tuple(start + timedelta(days=i) for i in range(closes.size))
    return History(dates=days, closes=closes)


def _gaussian(n: int, annual_vol: float, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, annual_vol / math.sqrt(TRADING_DAYS_PER_YEAR), size=n)


# ---------------------------------------------------------------------------
# Random walk — known answers
# ---------------------------------------------------------------------------
def test_the_random_walk_recovers_the_volatility_it_was_given() -> None:
    history = _history(_gaussian(3000, annual_vol=0.30))
    prediction = random_walk(history, horizon_days=HORIZON)
    annualised = prediction.sigma * math.sqrt(TRADING_DAYS_PER_YEAR / HORIZON)
    assert annualised == pytest.approx(0.30, abs=0.02)


def test_the_random_walk_scales_with_the_square_root_of_the_horizon() -> None:
    history = _history(_gaussian(2000, annual_vol=0.25))
    one = random_walk(history, horizon_days=1).sigma
    four = random_walk(history, horizon_days=4).sigma
    assert four == pytest.approx(2.0 * one, rel=1e-12)


def test_the_random_walk_drift_is_zero_even_on_a_strongly_trending_series() -> None:
    """Estimating drift from a year of daily data adds variance and no signal, and
    a baseline that beats itself by accident is worse than none."""
    trending = _gaussian(1000, annual_vol=0.20) + 0.002
    assert random_walk(_history(trending), horizon_days=HORIZON).mean == 0.0


def test_a_short_history_is_refused_rather_than_guessed() -> None:
    with pytest.raises(BaselineError, match="needs 60 returns"):
        random_walk(_history(_gaussian(20, 0.2)), horizon_days=HORIZON)


# ---------------------------------------------------------------------------
# The look-ahead guard
# ---------------------------------------------------------------------------
def test_before_keeps_only_strictly_earlier_bars() -> None:
    """The cutoff day itself is excluded: a forecast opening that morning cannot
    use that day's close."""
    history = _history(_gaussian(100, 0.2), start=date(2024, 1, 1))
    cutoff = date(2024, 2, 1)
    trimmed = history.before(cutoff)
    assert all(d < cutoff for d in trimmed.dates)
    assert max(trimmed.dates) == cutoff - timedelta(days=1)


def test_trimming_changes_the_estimate_it_feeds() -> None:
    """If it did not, the guard would be decorative."""
    calm = _gaussian(400, annual_vol=0.10, seed=1)
    wild = _gaussian(400, annual_vol=0.60, seed=2)
    history = _history(np.concatenate([calm, wild]))
    cutoff = history.dates[401]
    full = random_walk(history, horizon_days=HORIZON).sigma
    early = random_walk(history.before(cutoff), horizon_days=HORIZON).sigma
    assert early < full


def test_history_rejects_mismatched_lengths() -> None:
    with pytest.raises(BaselineError, match="different lengths"):
        History(dates=(date(2024, 1, 1),), closes=np.array([1.0, 2.0]))


def test_history_rejects_a_non_positive_close() -> None:
    """Log returns of a zero price are silently infinite."""
    with pytest.raises(BaselineError, match="non-positive close"):
        History(dates=(date(2024, 1, 1), date(2024, 1, 2)), closes=np.array([1.0, 0.0]))


# ---------------------------------------------------------------------------
# GARCH
# ---------------------------------------------------------------------------
def test_garch_recovers_the_volatility_of_a_homoskedastic_series() -> None:
    """With no clustering to find, it must agree with the trailing estimate."""
    history = _history(_gaussian(1200, annual_vol=0.25, seed=3))
    fitted = garch(history, horizon_days=HORIZON)
    walk = random_walk(history, horizon_days=HORIZON)
    assert fitted.sigma == pytest.approx(walk.sigma, rel=0.35)


def test_garch_forecasts_higher_volatility_after_a_turbulent_stretch() -> None:
    """The whole content of the model: tomorrow's variance is not the long run's."""
    rng = np.random.default_rng(5)
    calm = rng.normal(0, 0.005, size=900)
    storm = rng.normal(0, 0.030, size=60)
    after_storm = garch(_history(np.concatenate([calm, storm])), horizon_days=HORIZON)
    after_calm = garch(_history(np.concatenate([storm, calm])), horizon_days=HORIZON)
    assert after_storm.sigma > after_calm.sigma


def test_garch_refuses_a_history_too_short_to_fit() -> None:
    with pytest.raises(BaselineError, match="needs 250 returns"):
        garch(_history(_gaussian(100, 0.2)), horizon_days=HORIZON)


def test_garch_sums_variance_over_the_horizon_rather_than_scaling_by_root_time() -> None:
    history = _history(_gaussian(1200, annual_vol=0.25, seed=7))
    one = garch(history, horizon_days=1).sigma
    five = garch(history, horizon_days=5).sigma
    assert one < five < math.sqrt(5.0) * one * 1.2


# ---------------------------------------------------------------------------
# The earnings multiplier
# ---------------------------------------------------------------------------
def _with_earnings_jumps(
    n: int, jump: float, every: int = 63, seed: int = 11
) -> tuple[np.ndarray, list[int]]:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0, 0.008, size=n)
    starts = list(range(every, n - 10, every))
    for s in starts:
        returns[s] += jump * rng.choice([-1.0, 1.0])
    return returns, starts


def test_the_multiplier_is_above_one_when_earnings_days_move_more() -> None:
    returns, starts = _with_earnings_jumps(1000, jump=0.06)
    history = _history(returns)
    days = [history.dates[s] for s in starts]
    assert earnings_multiplier(history, days, horizon_days=HORIZON) > 1.5


def test_the_multiplier_is_near_one_when_earnings_days_are_ordinary() -> None:
    returns, starts = _with_earnings_jumps(1000, jump=0.0)
    history = _history(returns)
    days = [history.dates[s] for s in starts]
    assert earnings_multiplier(history, days, horizon_days=HORIZON) == pytest.approx(1.0, abs=0.6)


def test_too_few_past_earnings_gives_a_neutral_multiplier() -> None:
    """A neutral factor is honest about knowing nothing; a global constant would
    smuggle in an average of other companies."""
    history = _history(_gaussian(500, 0.2))
    assert earnings_multiplier(history, [history.dates[10]], horizon_days=HORIZON) == 1.0


def test_earnings_dates_outside_the_history_are_ignored() -> None:
    history = _history(_gaussian(500, 0.2))
    assert earnings_multiplier(history, [date(1990, 1, 1)], horizon_days=HORIZON) == 1.0


def test_the_scaled_walk_is_wider_than_the_plain_one() -> None:
    returns, starts = _with_earnings_jumps(1000, jump=0.06)
    history = _history(returns)
    days = [history.dates[s] for s in starts]
    plain = random_walk(history, horizon_days=HORIZON)
    scaled = earnings_scaled_random_walk(history, days, horizon_days=HORIZON)
    assert scaled.sigma > plain.sigma
    assert scaled.mean == 0.0


def test_the_scaled_walk_matches_the_plain_one_without_earnings_evidence() -> None:
    history = _history(_gaussian(500, 0.2))
    plain = random_walk(history, horizon_days=HORIZON)
    scaled = earnings_scaled_random_walk(history, [], horizon_days=HORIZON)
    assert scaled.sigma == pytest.approx(plain.sigma)


# ---------------------------------------------------------------------------
# The shared contract
# ---------------------------------------------------------------------------
def test_a_prediction_rejects_a_non_positive_sigma() -> None:
    """A zero-width forecast scores infinitely well or infinitely badly."""
    with pytest.raises(BaselineError, match="non-positive sigma"):
        Prediction(mean=0.0, sigma=0.0, name="broken")


def test_a_prediction_rejects_a_non_finite_mean() -> None:
    with pytest.raises(BaselineError, match="non-finite mean"):
        Prediction(mean=float("nan"), sigma=0.1, name="broken")


def test_every_baseline_names_itself_for_the_report() -> None:
    returns, starts = _with_earnings_jumps(1200, jump=0.05)
    history = _history(returns)
    days = [history.dates[s] for s in starts]
    names = {
        random_walk(history, horizon_days=HORIZON).name,
        garch(history, horizon_days=HORIZON).name,
        earnings_scaled_random_walk(history, days, horizon_days=HORIZON).name,
    }
    assert names == {"random_walk", "garch", "earnings_scaled_random_walk"}


def test_a_non_finite_garch_forecast_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A silently NaN variance would produce a sigma of nan and score as missing."""
    import arch

    class _Forecast:
        variance = type("F", (), {"to_numpy": staticmethod(lambda: np.full((1, 5), np.nan))})()

    class _Fitted:
        def forecast(self, **kwargs: object) -> _Forecast:
            return _Forecast()

    class _Model:
        def fit(self, **kwargs: object) -> _Fitted:
            return _Fitted()

    monkeypatch.setattr(arch, "arch_model", lambda *a, **k: _Model())
    with pytest.raises(BaselineError, match="non-finite variance"):
        garch(_history(_gaussian(400, 0.2)), horizon_days=HORIZON)


def test_a_flat_ordinary_series_gives_a_neutral_multiplier() -> None:
    """Dividing by a zero baseline dispersion would be infinite, not informative."""
    history = _history(np.zeros(500))
    days = [history.dates[s] for s in range(63, 400, 63)]
    assert earnings_multiplier(history, days, horizon_days=HORIZON) == 1.0
