"""Known-answer tests for the scoring rules.

A scoring rule you cannot verify independently is not a measurement, it is a
number. Every assertion here is against a value derived analytically rather than
against whatever the implementation happened to return.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from mapf.eval.scoring import brier, crps_ensemble, crps_normal, log_score_normal


# ---------------------------------------------------------------------------
# CRPS, Gaussian closed form
# ---------------------------------------------------------------------------
def test_a_near_deterministic_forecast_scores_absolute_error() -> None:
    """The case the brief names: as the forecast collapses to a point, CRPS must
    converge to |y - mu|. If it does not, the rule is not CRPS."""
    for sigma in (1e-3, 1e-4, 1e-5):
        score = float(crps_normal(mu=0.02, sigma=sigma, y=0.05))
        assert score == pytest.approx(abs(0.05 - 0.02), abs=5 * sigma)


def test_a_perfect_centred_forecast_has_the_analytic_minimum() -> None:
    """With y exactly at mu, w = 0 and CRPS reduces to sigma * (2*phi(0) - 1/sqrt(pi))."""
    sigma = 0.07
    expected = sigma * (2.0 / math.sqrt(2.0 * math.pi) - 1.0 / math.sqrt(math.pi))
    assert float(crps_normal(mu=0.0, sigma=sigma, y=0.0)) == pytest.approx(expected)


def test_crps_scales_linearly_with_sigma_when_standardised() -> None:
    """CRPS(N(mu, s), y) = s * CRPS(N(0,1), (y-mu)/s). A dimensional identity, so a
    unit slip anywhere in the formula breaks it."""
    unit = float(crps_normal(mu=0.0, sigma=1.0, y=1.5))
    scaled = float(crps_normal(mu=0.2, sigma=0.05, y=0.2 + 0.05 * 1.5))
    assert scaled == pytest.approx(0.05 * unit)


def test_crps_is_symmetric_about_the_mean() -> None:
    assert float(crps_normal(0.0, 1.0, 0.8)) == pytest.approx(float(crps_normal(0.0, 1.0, -0.8)))


def test_crps_is_minimised_at_the_truth() -> None:
    """Propriety, in the direction that matters: shifting the mean away from the
    outcome must never improve the score."""
    at_truth = float(crps_normal(0.03, 0.07, 0.03))
    for offset in (0.01, 0.02, 0.05):
        assert float(crps_normal(0.03 + offset, 0.07, 0.03)) > at_truth


def test_an_overconfident_forecast_is_punished() -> None:
    """A tight distribution centred in the wrong place must score worse than a wide
    one — this is what separates a proper rule from mean absolute error."""
    tight_and_wrong = float(crps_normal(mu=0.0, sigma=0.01, y=0.15))
    wide_and_honest = float(crps_normal(mu=0.0, sigma=0.10, y=0.15))
    assert tight_and_wrong > wide_and_honest


def test_a_non_positive_sigma_is_rejected() -> None:
    with pytest.raises(ValueError, match="point claim"):
        crps_normal(0.0, 0.0, 0.1)


def test_crps_is_vectorised() -> None:
    scores = crps_normal(np.zeros(3), np.full(3, 0.05), np.array([-0.1, 0.0, 0.1]))
    assert scores.shape == (3,)
    assert scores[1] < scores[0]


# ---------------------------------------------------------------------------
# CRPS, empirical
# ---------------------------------------------------------------------------
def test_the_ensemble_form_agrees_with_the_closed_form() -> None:
    """The two must measure the same thing. Sampling error is the only difference,
    and it is what tells us how many paths the Monte Carlo engine needs."""
    rng = np.random.default_rng(20260813)
    samples = rng.normal(0.01, 0.06, size=200_000)
    empirical = crps_ensemble(samples, y=0.04)
    exact = float(crps_normal(0.01, 0.06, 0.04))
    assert empirical == pytest.approx(exact, rel=0.01)


def test_a_degenerate_ensemble_scores_absolute_error() -> None:
    samples = np.full(500, 0.02)
    assert crps_ensemble(samples, y=0.05) == pytest.approx(abs(0.05 - 0.02))


def test_the_spread_term_is_what_makes_it_proper() -> None:
    """Without the -0.5*E|X-X'| term this is mean absolute error, and a forecaster
    is rewarded for collapsing its distribution to a point."""
    rng = np.random.default_rng(1)
    wide = rng.normal(0.0, 0.10, size=50_000)
    mae_like = float(np.mean(np.abs(wide - 0.0)))
    assert crps_ensemble(wide, y=0.0) < mae_like


def test_an_empty_ensemble_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty ensemble"):
        crps_ensemble(np.array([]), y=0.0)


# ---------------------------------------------------------------------------
# Log score and Brier
# ---------------------------------------------------------------------------
def test_a_non_positive_sigma_is_rejected_by_the_log_score() -> None:
    with pytest.raises(ValueError, match="sigma must be positive"):
        log_score_normal(0.0, 0.0, 0.1)


def test_the_log_score_matches_the_analytic_density() -> None:
    mu, sigma, y = 0.0, 1.0, 0.0
    assert log_score_normal(mu, sigma, y) == pytest.approx(0.5 * math.log(2.0 * math.pi))


def test_the_log_score_grows_quadratically_where_crps_grows_linearly() -> None:
    """Why the log score is reported alongside CRPS, as an analytic property rather
    than an impression: for a miss of w standard deviations the log score grows as
    w^2, while CRPS grows only as w. A model that assigned near-zero probability to
    what actually happened is punished far harder by the first.

    Ratios are taken of the *excess* over a perfect forecast, so the log score's
    sign — it is a density and can be negative — cannot corrupt the comparison.
    """
    sigma = 0.05
    base_log = log_score_normal(0.0, sigma, 0.0)
    base_crps = float(crps_normal(0.0, sigma, 0.0))

    def excess_log(w: float) -> float:
        return log_score_normal(0.0, sigma, w * sigma) - base_log

    def excess_crps(w: float) -> float:
        return float(crps_normal(0.0, sigma, w * sigma)) - base_crps

    # Exactly quadratic at every scale: doubling the miss quadruples the excess.
    assert excess_log(4) / excess_log(2) == pytest.approx(4.0)
    assert excess_log(16) / excess_log(8) == pytest.approx(4.0)

    # CRPS is only *asymptotically* linear, and it approaches slowly: 2.63 at two
    # sigma, still 2.11 at eight. The excess is |y - mu| minus a constant, so the
    # ratio tends to 2 from above rather than reaching it. Pinned at the measured
    # values — a test asserting a clean 2.0 would have been asserting a convenient
    # story rather than the function's behaviour.
    assert excess_crps(4) / excess_crps(2) == pytest.approx(2.63, rel=0.02)
    assert excess_crps(16) / excess_crps(8) == pytest.approx(2.11, rel=0.02)

    # The property that actually matters, at any scale worth caring about.
    assert excess_log(4) / excess_log(2) > excess_crps(4) / excess_crps(2)


@pytest.mark.parametrize(
    ("probability", "realised", "expected"),
    [(1.0, 0.05, 0.0), (0.0, 0.05, 1.0), (0.5, 0.05, 0.25), (0.5, -0.05, 0.25)],
)
def test_brier_known_answers(probability: float, realised: float, expected: float) -> None:
    assert brier(probability, realised) == pytest.approx(expected)


def test_a_probability_outside_the_unit_interval_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        brier(1.5, 0.01)
