"""Volatility compression: how far M.A.P.'s σ moves with a baseline's across names.

A forecaster whose volatilities were right on average and right across names would
give a slope of 1.0 when log σ(M.A.P.) is regressed on the log σ of a well-fitted
baseline. Record 5 found 0.32 on development; records 6, 8 and 9 (the git notes on
`ad71b13`) registered its replication on the second band and fixed the estimator
this module implements.

**The raw slope is not the estimate.** The baseline's σ is itself fitted, and error
in a regressor biases its slope towards zero, so the forward slope is a lower bound
on the truth and the inverse of the reverse slope an upper one — the Frisch bounds.
Record 8 corrects the forward slope by the baseline's reliability λ, estimated as the
correlation between two baselines fitted independently to the same history. Both are
fitted on the SAME prices, so their errors correlate, which inflates λ and shrinks
the correction: it is conservative against the compression claim.

**The claim is an interval, not a point.** Record 8 made the replication criterion
the widest defensible interval — the forward slope's lower bound to the reverse
slope's upper — excluding 1.0, because every source of uncertainty is stacked in it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from mapf.eval.aggregate import AggregationError, Floats, Ints
from mapf.eval.power import block_resamples, occupied_blocks


def _log_sigma(sigma: Floats, name: str) -> NDArray[np.float64]:
    values = np.asarray(sigma, dtype=np.float64)
    if values.size < 3:
        raise AggregationError(f"{name}: a slope needs at least three items, got {values.size}")
    if not np.all(np.isfinite(values)) or np.any(values <= 0.0):
        # A σ of zero is a forecast that claims certainty; its log is minus infinity
        # and would quietly decide any regression it entered.
        raise AggregationError(f"{name}: every σ must be finite and positive")
    return np.log(values)


def slope(x: NDArray[np.float64], y: NDArray[np.float64]) -> float:
    """Least-squares slope of `y` on `x`."""
    centred = x - x.mean()
    spread = float(centred @ centred)
    if spread <= 0.0:
        raise AggregationError("the regressor does not vary, so the slope is undefined")
    return float(centred @ (y - y.mean())) / spread


def _statistics(
    log_map: NDArray[np.float64],
    log_base: NDArray[np.float64],
    log_reference: NDArray[np.float64],
) -> tuple[float, float, float, float]:
    """Forward slope, inverse reverse slope, λ, corrected slope — on one sample."""
    forward = slope(log_base, log_map)
    reverse = slope(log_map, log_base)
    if reverse == 0.0:
        raise AggregationError("the reverse slope is zero, so its inverse is undefined")
    reliability = float(np.corrcoef(log_base, log_reference)[0, 1])
    if not reliability > 0.0:
        # Two fits of one volatility that do not correlate positively measure nothing
        # in common; dividing by that would not be a correction.
        raise AggregationError(f"reliability {reliability:.4f} is not positive")
    return forward, 1.0 / reverse, reliability, forward / reliability


Bounds = tuple[float, float]


@dataclass(frozen=True)
class Compression:
    """Record 8's quantities for one baseline, each with its clustered interval."""

    forward: float
    forward_ci: Bounds
    inverse_reverse: float
    inverse_reverse_ci: Bounds
    reliability: float
    reliability_ci: Bounds
    corrected: float
    corrected_ci: Bounds
    spread_ratio: float
    n: int
    date_clusters: int

    @property
    def frisch(self) -> Bounds:
        """Where the true slope lies if the only error is measurement error, before
        any sampling error is added."""
        return (self.forward, self.inverse_reverse)

    @property
    def widest(self) -> Bounds:
        """The replication criterion of record 8: every source of uncertainty stacked."""
        return (self.forward_ci[0], self.inverse_reverse_ci[1])

    @property
    def verdict(self) -> str:
        """Read off the widest interval, as registered — not off the corrected point,
        whose own interval can exclude 1.0 when the widest does not (GARCH on
        development, record 9)."""
        lower, upper = self.widest
        if upper < 1.0:
            return "compressed"
        if lower > 1.0:
            return "over-spread"
        return "indistinguishable from a slope of 1.0"


def compression_interval(
    map_sigma: Floats,
    baseline_sigma: Floats,
    day_index: Ints,
    *,
    reference_sigma: Floats,
    horizon_days: int = 5,
    draws: int = 4000,
    seed: int = 20260813,
    confidence: float = 0.95,
) -> Compression:
    """Record 8's estimator against `baseline_sigma`, with percentile intervals.

    `reference_sigma` is the OTHER baseline, fitted independently to the same prices;
    its correlation with `baseline_sigma` in log is λ. The pairing is symmetric, so
    random walk against GARCH and GARCH against random walk give one λ.

    λ is re-estimated inside every resample rather than held at its point value.
    The registration did not say which, and the record does: re-estimating is what
    reproduces record 8's development interval [0.3144, 0.4659] to four decimals,
    where a fixed λ gives [0.3102, 0.4532]. It is also the honest one — λ is
    estimated from the same sample, and fixing it would leave its uncertainty out.

    The draws, the seed and the ten-day blocks are the ones records 2 and 4 fixed and
    record 8 reused, spelled out as defaults for the same reason as the tail ratio's.
    """
    log_map = _log_sigma(map_sigma, "map_sigma")
    log_base = _log_sigma(baseline_sigma, "baseline_sigma")
    log_reference = _log_sigma(reference_sigma, "reference_sigma")
    days = np.asarray(day_index, dtype=np.int64)
    if not (log_map.size == log_base.size == log_reference.size == days.size):
        raise AggregationError(
            f"compression inputs disagree in length: map={log_map.size}, "
            f"baseline={log_base.size}, reference={log_reference.size}, days={days.size}"
        )
    forward, inverse_reverse, reliability, corrected = _statistics(log_map, log_base, log_reference)
    drawn: list[tuple[float, float, float, float]] = []
    rng = np.random.default_rng(seed)
    for index in block_resamples(days, rng, draws=draws, block_days=horizon_days * 2):
        try:
            drawn.append(_statistics(log_map[index], log_base[index], log_reference[index]))
        except AggregationError:
            # A resample on which a slope or λ is undefined. Dropped rather than
            # invented, and refused below if nothing survives.
            continue
    if not drawn:
        raise AggregationError("no bootstrap resample produced defined slopes")
    tail = (1.0 - confidence) / 2.0 * 100.0
    columns = np.asarray(drawn, dtype=np.float64)
    bounds = np.percentile(columns, [tail, 100.0 - tail], axis=0)

    def ci(column: int) -> Bounds:
        return (float(bounds[0, column]), float(bounds[1, column]))

    return Compression(
        forward=forward,
        forward_ci=ci(0),
        inverse_reverse=inverse_reverse,
        inverse_reverse_ci=ci(1),
        reliability=reliability,
        reliability_ci=ci(2),
        corrected=corrected,
        corrected_ci=ci(3),
        spread_ratio=float(np.std(log_map) / np.std(log_base)),
        n=int(log_map.size),
        date_clusters=occupied_blocks(days, horizon_days * 2),
    )
