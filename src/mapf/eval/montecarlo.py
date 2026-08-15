"""Monte Carlo over the three-scenario mixture.

M.A.P. emits three weighted scenarios, each with a return and an annualised
volatility. Three point estimates are not a distribution — that was one of the
original design's errors — so this is what turns them into one.

Each scenario is a geometric Brownian motion: drift chosen so the *expected*
horizon log-return matches the scenario's stated return, diffusion from its
annualised volatility. Paths are drawn per scenario in proportion to its weight,
and pooled. The pooled sample is the predictive distribution everything downstream
scores against.

Two decisions worth stating.

**The mixture is sampled, not averaged.** Averaging the three scenarios into one
Gaussian would discard exactly what makes the forecast interesting: a bimodal view
where the model says "either a beat or a miss, not much in between" collapses into
a single wide bell, and the fan chart would show an outcome the model never
predicted.

**Volatility is annualised on input and scaled here.** The schema stores annualised
volatility so a number is comparable across horizons (ADR 0016); the scaling to the
horizon happens once, here, rather than at every call site.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from mapf.core.errors import MapError
from mapf.core.models import ScenarioSet

TRADING_DAYS_PER_YEAR = 252
DEFAULT_PATHS = 20_000


class SimulationError(MapError):
    """The mixture could not be simulated."""


@dataclass(frozen=True)
class Simulation:
    """A sampled predictive distribution of the horizon return."""

    returns: NDArray[np.float64]
    horizon_days: int
    paths: int
    seed: int

    @property
    def mean(self) -> float:
        return float(np.mean(self.returns))

    @property
    def sigma(self) -> float:
        return float(np.std(self.returns, ddof=1))

    def quantiles(self, levels: tuple[float, ...]) -> tuple[float, ...]:
        """Fan-chart bands. Levels are fractions, not percentages."""
        if any(not 0.0 < q < 1.0 for q in levels):
            raise SimulationError(f"quantile levels must lie in (0, 1): {levels}")
        return tuple(float(v) for v in np.quantile(self.returns, levels))

    def probability_above(self, threshold: float) -> float:
        """P(return > threshold). The directional claim, scored with Brier."""
        return float(np.mean(self.returns > threshold))

    def prices(self, spot: float) -> NDArray[np.float64]:
        if spot <= 0.0:
            raise SimulationError(f"spot must be positive, got {spot}")
        return np.asarray(spot * np.exp(self.returns), dtype=np.float64)


def _allocate(weights: NDArray[np.float64], paths: int) -> NDArray[np.int64]:
    """Split `paths` across scenarios by largest remainder.

    Deterministic, not a multinomial draw. A multinomial gives each scenario its
    share only *in expectation*, so two runs of the same forecast would produce
    slightly different fan charts — and a chart that moves when nothing changed is
    indefensible in a project whose whole claim is reproducibility. Largest
    remainder gives a 25% scenario exactly a quarter of the paths, with the
    rounding leftovers going to the scenarios that were cut hardest.
    """
    exact = weights * paths
    counts = np.floor(exact).astype(np.int64)
    shortfall = paths - int(counts.sum())
    if shortfall:
        # Ties broken by scenario order, which is fixed, so this stays deterministic.
        order = np.argsort(-(exact - counts), kind="stable")
        counts[order[:shortfall]] += 1
    return counts


def simulate(
    scenarios: ScenarioSet,
    *,
    horizon_days: int,
    paths: int = DEFAULT_PATHS,
    seed: int = 20260813,
) -> Simulation:
    """Sample the weighted mixture of scenario GBMs.

    Returns are **log** returns over the horizon, which is what the scoring rules
    consume. The seed is recorded on the result: a fan chart nobody can reproduce
    is a picture, not a measurement.
    """
    if horizon_days < 1:
        raise SimulationError(f"horizon_days must be at least 1, got {horizon_days}")
    if paths < 1:
        raise SimulationError(f"paths must be at least 1, got {paths}")

    ordered = (scenarios.bullish, scenarios.base_case, scenarios.bearish)
    weights = np.array([s.probability_weight for s in ordered], dtype=np.float64)
    total = float(weights.sum())
    if total <= 0.0:
        raise SimulationError("scenario weights sum to zero")
    weights = weights / total

    rng = np.random.default_rng(seed)
    counts = _allocate(weights, paths)

    years = horizon_days / TRADING_DAYS_PER_YEAR
    chunks: list[NDArray[np.float64]] = []
    for scenario, count in zip(ordered, counts, strict=True):
        if count == 0:
            continue
        sigma = scenario.annualised_vol * math.sqrt(years)
        # log(1 + r) is the log-return the scenario's stated simple return implies;
        # the -sigma^2/2 term makes the *expected simple return* match it rather
        # than exceeding it by the convexity of the exponential.
        target = math.log1p(scenario.price_return)
        drift = target - 0.5 * sigma**2
        chunks.append(rng.normal(drift, sigma, size=int(count)))

    pooled = np.concatenate(chunks) if chunks else np.zeros(0)
    if pooled.size != paths:
        raise SimulationError(f"expected {paths} paths, produced {pooled.size}")
    return Simulation(
        returns=np.asarray(pooled, dtype=np.float64),
        horizon_days=horizon_days,
        paths=paths,
        seed=seed,
    )


def crps_against(simulation: Simulation, realised: float) -> float:
    """CRPS of the simulated distribution against what happened.

    Uses the empirical form, so the mixture is scored as the mixture rather than
    as a Gaussian fitted to it — the whole reason for sampling in the first place.
    """
    from mapf.eval.scoring import crps_ensemble

    return crps_ensemble(simulation.returns, realised)
