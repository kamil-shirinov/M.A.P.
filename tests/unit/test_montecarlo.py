"""The Monte Carlo mixture.

Three point estimates are not a distribution. These assertions check that the
sampled object is genuinely the mixture — that it preserves what averaging would
destroy, and reproduces exactly.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from mapf.eval.montecarlo import (
    TRADING_DAYS_PER_YEAR,
    SimulationError,
    crps_against,
    simulate,
    simulate_paths,
)
from tests.conftest import make_scenario_set

HORIZON = 5


# ---------------------------------------------------------------------------
# Known answers
# ---------------------------------------------------------------------------
def test_a_single_effective_scenario_recovers_its_own_volatility() -> None:
    """All weight on the base case: the mixture must be that scenario, exactly."""
    scenarios = make_scenario_set(
        weights=(0.0, 1.0, 0.0), modifiers=(0.05, 0.0, -0.05), vols=(0.3, 0.24, 0.3)
    )
    sim = simulate(scenarios, horizon_days=HORIZON, paths=200_000)
    expected = 0.24 * math.sqrt(HORIZON / TRADING_DAYS_PER_YEAR)
    assert sim.sigma == pytest.approx(expected, rel=0.02)


def test_the_expected_simple_return_matches_the_scenario() -> None:
    """The -sigma^2/2 term exists so the mean simple return is the stated one
    rather than exceeding it by the convexity of the exponential."""
    scenarios = make_scenario_set(
        weights=(0.0, 1.0, 0.0), modifiers=(0.10, 0.04, -0.02), vols=(0.3, 0.30, 0.3)
    )
    sim = simulate(scenarios, horizon_days=HORIZON, paths=400_000)
    simple = float(np.mean(np.exp(sim.returns) - 1.0))
    assert simple == pytest.approx(0.04, abs=0.003)


def test_volatility_scales_with_the_square_root_of_the_horizon() -> None:
    scenarios = make_scenario_set(
        weights=(0.0, 1.0, 0.0), modifiers=(0.05, 0.0, -0.05), vols=(0.3, 0.30, 0.3)
    )
    one = simulate(scenarios, horizon_days=1, paths=200_000).sigma
    four = simulate(scenarios, horizon_days=4, paths=200_000).sigma
    assert four == pytest.approx(2.0 * one, rel=0.03)


def test_weights_determine_the_share_of_paths_exactly() -> None:
    """Multinomial, not per-path categorical: a 25% scenario gets 25% of paths
    rather than 25% in expectation, so a fan chart cannot drift between runs."""
    scenarios = make_scenario_set(
        weights=(0.25, 0.50, 0.25), modifiers=(0.5, 0.0, -0.5), vols=(0.01, 0.01, 0.01)
    )
    sim = simulate(scenarios, horizon_days=HORIZON, paths=1000)
    # Near-zero vol makes each scenario a spike; count which spike each path is at.
    up = int(np.sum(sim.returns > 0.2))
    down = int(np.sum(sim.returns < -0.2))
    assert up == 250
    assert down == 250


# ---------------------------------------------------------------------------
# What averaging would destroy
# ---------------------------------------------------------------------------
def test_a_bimodal_view_stays_bimodal() -> None:
    """Collapsing to one Gaussian would render an outcome the model never
    predicted: a fat middle where it said 'a beat or a miss, not much between'."""
    scenarios = make_scenario_set(
        weights=(0.5, 0.0, 0.5), modifiers=(0.10, 0.001, -0.10), vols=(0.10, 0.10, 0.10)
    )
    sim = simulate(scenarios, horizon_days=HORIZON, paths=100_000)
    middle = float(np.mean(np.abs(sim.returns) < 0.02))
    tails = float(np.mean(np.abs(sim.returns) > 0.06))
    assert tails > middle * 3


def test_the_mixture_is_wider_than_any_single_scenario() -> None:
    scenarios = make_scenario_set(
        weights=(0.4, 0.2, 0.4), modifiers=(0.08, 0.0, -0.08), vols=(0.2, 0.2, 0.2)
    )
    sim = simulate(scenarios, horizon_days=HORIZON, paths=100_000)
    single = 0.2 * math.sqrt(HORIZON / TRADING_DAYS_PER_YEAR)
    assert sim.sigma > single


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
def test_the_same_seed_reproduces_the_same_sample() -> None:
    """A fan chart nobody can reproduce is a picture, not a measurement."""
    scenarios = make_scenario_set()
    a = simulate(scenarios, horizon_days=HORIZON, paths=5000, seed=7)
    b = simulate(scenarios, horizon_days=HORIZON, paths=5000, seed=7)
    assert np.array_equal(a.returns, b.returns)


def test_a_different_seed_gives_a_different_sample() -> None:
    scenarios = make_scenario_set()
    a = simulate(scenarios, horizon_days=HORIZON, paths=5000, seed=1)
    b = simulate(scenarios, horizon_days=HORIZON, paths=5000, seed=2)
    assert not np.array_equal(a.returns, b.returns)


def test_the_seed_is_recorded_on_the_result() -> None:
    sim = simulate(make_scenario_set(), horizon_days=HORIZON, paths=100, seed=99)
    assert (sim.seed, sim.paths, sim.horizon_days) == (99, 100, HORIZON)


# ---------------------------------------------------------------------------
# Reading the distribution
# ---------------------------------------------------------------------------
def test_quantiles_are_ordered_and_bracket_the_median() -> None:
    sim = simulate(make_scenario_set(), horizon_days=HORIZON, paths=50_000)
    lo, mid, hi = sim.quantiles((0.05, 0.5, 0.95))
    assert lo < mid < hi


def test_quantile_levels_outside_the_unit_interval_are_rejected() -> None:
    sim = simulate(make_scenario_set(), horizon_days=HORIZON, paths=100)
    with pytest.raises(SimulationError, match="must lie in"):
        sim.quantiles((0.0, 1.0))


def test_probability_above_agrees_with_the_weights_for_spiked_scenarios() -> None:
    scenarios = make_scenario_set(
        weights=(0.3, 0.0, 0.7), modifiers=(0.2, 0.0, -0.2), vols=(0.01, 0.01, 0.01)
    )
    sim = simulate(scenarios, horizon_days=HORIZON, paths=10_000)
    assert sim.probability_above(0.0) == pytest.approx(0.3, abs=0.01)


def test_prices_exponentiate_the_log_returns() -> None:
    # An odd path count so the median is an actual sample rather than an average
    # of two: exp() does not commute with the interpolation numpy does otherwise.
    sim = simulate(make_scenario_set(), horizon_days=HORIZON, paths=1001)
    prices = sim.prices(100.0)
    assert prices.min() > 0.0
    assert float(np.median(prices)) == pytest.approx(
        100.0 * math.exp(float(np.median(sim.returns))), rel=1e-9
    )


def test_a_non_positive_spot_is_rejected() -> None:
    sim = simulate(make_scenario_set(), horizon_days=HORIZON, paths=100)
    with pytest.raises(SimulationError, match="spot must be positive"):
        sim.prices(0.0)


# ---------------------------------------------------------------------------
# Scoring the sample
# ---------------------------------------------------------------------------
def test_crps_against_scores_the_mixture_not_a_fitted_gaussian() -> None:
    """A bimodal forecast that straddles the outcome must score worse than a
    unimodal one centred on it, even with the same mean and a similar spread."""
    outcome = 0.0
    bimodal = simulate(
        make_scenario_set(
            weights=(0.5, 0.0, 0.5), modifiers=(0.10, 0.001, -0.10), vols=(0.05, 0.05, 0.05)
        ),
        horizon_days=HORIZON,
        paths=40_000,
    )
    unimodal = simulate(
        make_scenario_set(
            weights=(0.0, 1.0, 0.0), modifiers=(0.05, 0.0, -0.05), vols=(0.05, 0.60, 0.05)
        ),
        horizon_days=HORIZON,
        paths=40_000,
    )
    assert crps_against(bimodal, outcome) > crps_against(unimodal, outcome)


def test_crps_is_lower_when_the_outcome_lands_where_the_mass_is() -> None:
    scenarios = make_scenario_set(
        weights=(0.0, 1.0, 0.0), modifiers=(0.10, 0.02, -0.05), vols=(0.2, 0.20, 0.2)
    )
    sim = simulate(scenarios, horizon_days=HORIZON, paths=40_000)
    assert crps_against(sim, 0.02) < crps_against(sim, 0.25)


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("horizon", "paths"), [(0, 100), (-1, 100)])
def test_a_non_positive_horizon_is_rejected(horizon: int, paths: int) -> None:
    with pytest.raises(SimulationError, match="horizon_days must be"):
        simulate(make_scenario_set(), horizon_days=horizon, paths=paths)


def test_a_non_positive_path_count_is_rejected() -> None:
    with pytest.raises(SimulationError, match="paths must be"):
        simulate(make_scenario_set(), horizon_days=HORIZON, paths=0)


def test_the_mean_is_exposed() -> None:
    sim = simulate(
        make_scenario_set(
            weights=(0.0, 1.0, 0.0), modifiers=(0.10, 0.02, -0.05), vols=(0.2, 0.20, 0.2)
        ),
        horizon_days=HORIZON,
        paths=200_000,
    )
    assert sim.mean == pytest.approx(math.log1p(0.02), abs=0.002)


def test_zero_total_weight_is_refused() -> None:
    """Normalising by zero would silently produce NaN weights."""
    scenarios = make_scenario_set()
    broken = scenarios.model_copy(
        update={
            "bullish": scenarios.bullish.model_copy(update={"probability_weight": 0.0}),
            "base_case": scenarios.base_case.model_copy(update={"probability_weight": 0.0}),
            "bearish": scenarios.bearish.model_copy(update={"probability_weight": 0.0}),
        }
    )
    with pytest.raises(SimulationError, match="sum to zero"):
        simulate(broken, horizon_days=HORIZON, paths=100)


def test_the_allocation_always_sums_to_the_requested_paths() -> None:
    """Largest-remainder rounding must not lose or invent a path."""
    from mapf.eval.montecarlo import _allocate

    for total in (1, 7, 99, 1000, 20_001):
        for weights in ([0.25, 0.5, 0.25], [1 / 3, 1 / 3, 1 / 3], [0.01, 0.98, 0.01]):
            counts = _allocate(np.array(weights), total)
            assert int(counts.sum()) == total
            assert all(c >= 0 for c in counts)


def test_a_broken_allocation_is_caught_rather_than_silently_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard exists for a future change to the allocator, not for today."""
    monkeypatch.setattr(
        "mapf.eval.montecarlo._allocate", lambda w, p: np.array([1, 1, 1], dtype=np.int64)
    )
    with pytest.raises(SimulationError, match="expected 100 paths, produced 3"):
        simulate(make_scenario_set(), horizon_days=HORIZON, paths=100)


# --- the fan's paths ------------------------------------------------------------


def test_the_paths_end_on_the_scored_sample_bit_for_bit() -> None:
    """The fan at the horizon must be the distribution the scorer scores, not a
    second sample of it."""
    scenarios = make_scenario_set()
    paths = simulate_paths(scenarios, horizon_days=5)
    scored = simulate(scenarios, horizon_days=5)
    assert np.array_equal(paths.returns[:, -1], scored.returns)
    assert paths.terminal.returns is not None
    assert np.array_equal(paths.terminal.returns, scored.returns)


def test_each_session_is_each_scenario_part_of_the_way_to_its_horizon() -> None:
    """Session t of h: mean u*drift and variance u*sigma^2 per scenario, u = t/h,
    mixed by weight. Checked against that closed form on a large sample."""
    scenarios = make_scenario_set()
    h = 5
    paths = simulate_paths(scenarios, horizon_days=h, paths=200_000)
    ordered = (scenarios.bullish, scenarios.base_case, scenarios.bearish)
    w = np.array([s.probability_weight for s in ordered])
    w = w / w.sum()
    sig = np.array([s.annualised_vol * math.sqrt(h / TRADING_DAYS_PER_YEAR) for s in ordered])
    drift = np.array([math.log1p(s.price_return) for s in ordered]) - 0.5 * sig**2
    for t in range(1, h + 1):
        u = t / h
        mean = float(w @ (u * drift))
        sd = math.sqrt(float(w @ (u * sig**2 + (u * drift) ** 2)) - mean**2)
        assert paths.means[t - 1] == pytest.approx(mean, abs=4e-4)
        assert paths.sigmas[t - 1] == pytest.approx(sd, rel=0.01)


def test_the_fan_widens_every_session() -> None:
    paths = simulate_paths(make_scenario_set(), horizon_days=21)
    assert np.all(np.diff(paths.sigmas) > 0)


def test_a_one_session_horizon_is_just_the_scored_sample() -> None:
    scenarios = make_scenario_set()
    paths = simulate_paths(scenarios, horizon_days=1)
    assert paths.returns.shape == (20_000, 1)
    assert np.array_equal(paths.returns[:, 0], simulate(scenarios, horizon_days=1).returns)


def test_the_quantiles_come_by_session_and_level() -> None:
    paths = simulate_paths(make_scenario_set(), horizon_days=5)
    grid = paths.quantiles((0.1, 0.5, 0.9))
    assert grid.shape == (5, 3)
    assert np.all(grid[:, 0] < grid[:, 1]) and np.all(grid[:, 1] < grid[:, 2])
    # At the horizon, the same numbers the terminal sample gives.
    assert grid[-1] == pytest.approx(paths.terminal.quantiles((0.1, 0.5, 0.9)))
    with pytest.raises(SimulationError, match="quantile levels"):
        paths.quantiles((0.0, 0.5))
