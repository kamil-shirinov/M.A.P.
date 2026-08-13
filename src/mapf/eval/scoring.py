"""Proper scoring rules.

Built before any M.A.P. numbers exist, deliberately. The brief orders baselines
before the scorer so that nobody sees M.A.P.'s score before there is something to
compare it to — the same logic applies here: a scoring rule written while looking
at the thing it scores is a scoring rule with a thumb on it.

Every function has a known-answer test. A scoring rule that cannot be verified
independently is not a measurement, it is a number.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray
from scipy.stats import norm

_INV_SQRT_PI = 1.0 / math.sqrt(math.pi)


def crps_normal(
    mu: NDArray[np.float64] | float,
    sigma: NDArray[np.float64] | float,
    y: NDArray[np.float64] | float,
) -> NDArray[np.float64]:
    """CRPS of a Gaussian predictive distribution, in closed form.

        CRPS(N(mu, sigma), y) = sigma * [ w(2*Phi(w) - 1) + 2*phi(w) - 1/sqrt(pi) ]

    with `w = (y - mu) / sigma`. Exact rather than sampled, which matters for the
    power analysis: Monte Carlo noise in the *scorer* would be mistaken for noise
    in the *forecast*.

    As sigma approaches zero this converges to |y - mu| — a deterministic forecast
    scored by absolute error, which is the known-answer case the brief demands.
    """
    mu_a = np.asarray(mu, dtype=np.float64)
    sigma_a = np.asarray(sigma, dtype=np.float64)
    y_a = np.asarray(y, dtype=np.float64)
    if np.any(sigma_a <= 0):
        raise ValueError("sigma must be positive; a zero-width forecast is a point claim")

    w = (y_a - mu_a) / sigma_a
    result = sigma_a * (w * (2.0 * norm.cdf(w) - 1.0) + 2.0 * norm.pdf(w) - _INV_SQRT_PI)
    return np.asarray(result, dtype=np.float64)


def crps_ensemble(samples: NDArray[np.float64], y: float) -> float:
    """CRPS of an empirical distribution given by samples.

        CRPS = E|X - y| - 0.5 * E|X - X'|

    The second term is what makes this a *proper* rule rather than mean absolute
    error: without it, a forecaster is rewarded for collapsing its distribution to
    a point. Computed from the sorted sample in O(n log n) rather than the O(n^2)
    pairwise form.
    """
    if samples.size == 0:
        raise ValueError("cannot score an empty ensemble")
    x = np.sort(np.asarray(samples, dtype=np.float64))
    n = x.size
    term_one = float(np.mean(np.abs(x - y)))
    # For sorted x, sum_{i<j} (x_j - x_i) == sum_i (2i - n + 1) * x_i, so
    # E|X - X'| = 2 * that / n^2 and the CRPS spread term is half of E|X - X'| —
    # the two factors of two cancel. Getting this wrong by a factor of 2 still
    # passes a degenerate-ensemble test, because the spread term is zero there;
    # only agreement with the closed form catches it.
    weights = 2.0 * np.arange(n, dtype=np.float64) - n + 1.0
    spread_half = float(np.sum(weights * x)) / (n * n)
    return term_one - spread_half


def log_score_normal(mu: float, sigma: float, y: float) -> float:
    """Negative log predictive density. Reported because it punishes tail misses.

    A model that assigns near-zero probability to what actually happened should be
    penalised heavily for it, and CRPS is comparatively forgiving there.
    """
    if sigma <= 0:
        raise ValueError("sigma must be positive")
    z = (y - mu) / sigma
    return 0.5 * z * z + math.log(sigma) + 0.5 * math.log(2.0 * math.pi)


def brier(probability_up: float, realised_return: float) -> float:
    """Brier score on direction. The interpretable one."""
    if not 0.0 <= probability_up <= 1.0:
        raise ValueError(f"probability must be in [0, 1], got {probability_up}")
    outcome = 1.0 if realised_return > 0 else 0.0
    return (probability_up - outcome) ** 2
