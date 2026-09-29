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

**Where the narrowness sits** is record 6's S3: the σ ratio on the largest realised
moves against the rest. The cut is on the realised return, which neither model
produced, so selecting on it cannot manufacture a small σ the way a cut on z would.
"""

from __future__ import annotations

import math
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


# Record 6: the development cuts of 11, 18 and 36 of 178, as fractions so they scale
# with whatever n a band yields.
CUT_FRACTIONS = (0.06, 0.10, 0.20)


def cut_size(fraction: float, n: int) -> int:
    """Items in a cut: the nearest whole number, halves rounded up.

    Record 6 fixed the fractions and not the rounding. Nearest is the reading that
    gives 11, 18 and 36 on development's 178, where the counts came from; rounding up
    gives the same there, and 36 rather than 35 at 20% of the second band's 177,
    which changes no verdict (Findings #66).
    """
    return math.floor(fraction * n + 0.5)


@dataclass(frozen=True)
class MoveCut:
    """Median σ ratio on the largest moves against the rest, with the difference's
    clustered interval."""

    fraction: float
    k: int
    top_median: float
    rest_median: float
    difference: float
    lower: float
    upper: float


def largest_move_cuts(
    map_sigma: Floats,
    baseline_sigma: Floats,
    realised_return: Floats,
    day_index: Ints,
    *,
    fractions: tuple[float, ...] = CUT_FRACTIONS,
    horizon_days: int = 5,
    draws: int = 4000,
    seed: int = 20260813,
    confidence: float = 0.95,
) -> tuple[MoveCut, ...]:
    """Record 6's S3: median σ(M.A.P.)/σ(baseline) on the top cut by |realised
    return| against the rest, at each fraction.

    Membership is decided once, on the whole panel, and each resample takes the
    medians of whichever members it drew. Re-choosing the top k inside every resample
    is the other reading; it is the one that does NOT reproduce record 5's development
    intervals, where this one does to four decimals. Each cut starts the generator
    from the seed afresh, which is also what reproduces them.

    Record 5 ran at 2,000 draws; record 6 registered the replication at 4,000, so the
    default is 4,000 and development's figures are reproduced by asking for 2,000.
    """
    ratio = np.exp(
        _log_sigma(map_sigma, "map_sigma") - _log_sigma(baseline_sigma, "baseline_sigma")
    )
    moves = np.abs(np.asarray(realised_return, dtype=np.float64))
    days = np.asarray(day_index, dtype=np.int64)
    if not (ratio.size == moves.size == days.size):
        raise AggregationError(
            f"cut inputs disagree in length: sigma={ratio.size}, "
            f"returns={moves.size}, days={days.size}"
        )
    if not np.all(np.isfinite(moves)):
        raise AggregationError("every realised return must be finite")
    order = np.argsort(-moves, kind="stable")
    tail = (1.0 - confidence) / 2.0 * 100.0
    cuts: list[MoveCut] = []
    for fraction in fractions:
        k = cut_size(fraction, ratio.size)
        if not 0 < k < ratio.size:
            raise AggregationError(
                f"a {fraction:.0%} cut of {ratio.size} items holds {k}, leaving no contrast"
            )
        top = np.zeros(ratio.size, dtype=bool)
        top[order[:k]] = True
        differences: list[float] = []
        rng = np.random.default_rng(seed)
        for index in block_resamples(days, rng, draws=draws, block_days=horizon_days * 2):
            drawn_top, drawn_rest = ratio[index][top[index]], ratio[index][~top[index]]
            if drawn_top.size and drawn_rest.size:
                differences.append(float(np.median(drawn_top) - np.median(drawn_rest)))
            # A resample that drew no member of one side has no contrast to offer.
        if not differences:
            raise AggregationError(f"no bootstrap resample drew both sides of the {k}-item cut")
        lower, upper = np.percentile(np.asarray(differences), [tail, 100.0 - tail])
        top_median, rest_median = float(np.median(ratio[top])), float(np.median(ratio[~top]))
        cuts.append(
            MoveCut(
                fraction=fraction,
                k=k,
                top_median=top_median,
                rest_median=rest_median,
                difference=top_median - rest_median,
                lower=float(lower),
                upper=float(upper),
            )
        )
    return tuple(cuts)


def monotone(cuts: tuple[MoveCut, ...]) -> bool:
    """Record 6's shape: the deeper the cut, the more negative the difference."""
    ordered = sorted(cuts, key=lambda cut: cut.fraction)
    return all(a.difference < b.difference for a, b in zip(ordered, ordered[1:], strict=False))
