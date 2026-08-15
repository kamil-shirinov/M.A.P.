"""Turning per-item scores into the numbers that get reported.

Three things happen here, and each exists because the naive version of it is wrong
in a way that flatters the result.

**Comparison is paired.** M.A.P. and the baseline see the same realised return, so
when the market drops three percent both score badly. Differencing per item removes
that common move; comparing separately-averaged scores would leave it in and the
interval would be dominated by market noise neither forecaster controls.

**The interval is clustered on calendar time, not on items.** Item 2.02 filings
land in reporting season, so many forecasts share days and overlapping windows. An
i.i.d. bootstrap over items would treat those as independent and return an interval
far too narrow — the same failure, differently dressed, as the empty-block defect
in ADR 0015. The resampler is the repaired one from `power`, not a second copy.

**A null result carries its power.** ADR 0015's rule: a confidence interval
spanning zero at 24% power says nothing about the world, so nothing here reports a
difference without the sample it came from.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from mapf.core.errors import MapError
from mapf.eval.power import moving_block_bootstrap, occupied_blocks

# Scores arrive either as plain lists or as arrays straight out of a scoring pass;
# insisting on one would push a conversion onto every caller.
Floats = Sequence[float] | NDArray[np.float64]
Ints = Sequence[int] | NDArray[np.int64]


class AggregationError(MapError):
    """Scores could not be aggregated into a reportable number."""


@dataclass(frozen=True)
class Comparison:
    """A paired comparison of one forecaster against one baseline."""

    name: str
    baseline: str
    n: int
    model_mean: float
    baseline_mean: float
    mean_difference: float
    lower: float
    upper: float
    date_clusters: int

    @property
    def relative_improvement(self) -> float:
        """Fraction of the baseline's score removed. Positive is better."""
        if self.baseline_mean == 0.0:
            return 0.0
        return -self.mean_difference / self.baseline_mean

    @property
    def significant(self) -> bool:
        """Whether the interval excludes zero. Never reported without `n`."""
        return self.lower > 0.0 or self.upper < 0.0

    @property
    def verdict(self) -> str:
        if not self.significant:
            return "indistinguishable"
        return "better" if self.mean_difference < 0.0 else "worse"


def compare(
    model_scores: Floats,
    baseline_scores: Floats,
    day_index: Ints,
    *,
    name: str,
    baseline: str,
    horizon_days: int = 5,
    draws: int = 2000,
    seed: int = 20260813,
    confidence: float = 0.95,
) -> Comparison:
    """Paired difference with a calendar-clustered bootstrap interval.

    `day_index` is each item's forecast start as an integer day offset — the axis
    the clustering runs on. Lower scores are better (CRPS, log score), so a
    negative difference means the model beat the baseline.
    """
    model = np.asarray(model_scores, dtype=np.float64)
    base = np.asarray(baseline_scores, dtype=np.float64)
    days = np.asarray(day_index, dtype=np.int64)
    if not (model.size == base.size == days.size):
        raise AggregationError(
            f"paired inputs disagree in length: model={model.size}, "
            f"baseline={base.size}, days={days.size}"
        )
    if model.size == 0:
        raise AggregationError("nothing to compare: no scored items")
    if not np.all(np.isfinite(model)) or not np.all(np.isfinite(base)):
        raise AggregationError("scores contain non-finite values")

    differences = model - base
    rng = np.random.default_rng(seed)
    # Blocks of twice the horizon, so two windows that overlap can land together.
    means = moving_block_bootstrap(
        differences, days, rng, draws=draws, block_days=horizon_days * 2
    )
    tail = (1.0 - confidence) / 2.0 * 100.0
    lower, upper = np.percentile(means, [tail, 100.0 - tail])
    return Comparison(
        name=name,
        baseline=baseline,
        n=int(model.size),
        model_mean=float(np.mean(model)),
        baseline_mean=float(np.mean(base)),
        mean_difference=float(np.mean(differences)),
        lower=float(lower),
        upper=float(upper),
        date_clusters=occupied_blocks(days, horizon_days * 2),
    )


@dataclass(frozen=True)
class LeakageEstimate:
    """Clean-band performance minus ambiguous-band performance.

    Reported as a *difference*, never as two results. If the model looks materially
    better on the contaminated band, that gap is the leakage — measured rather than
    disclaimed (ADR 0018).
    """

    clean_mean: float
    ambiguous_mean: float
    difference: float
    lower: float
    upper: float
    clean_n: int
    ambiguous_n: int

    @property
    def suggests_leakage(self) -> bool:
        """Contamination makes the ambiguous band score *better*, so lower."""
        return self.lower > 0.0


def leakage(
    clean_scores: Floats,
    ambiguous_scores: Floats,
    *,
    draws: int = 2000,
    seed: int = 20260813,
    confidence: float = 0.95,
) -> LeakageEstimate:
    """Unpaired difference of band means, bootstrapped within each band.

    Unpaired because the two bands are different dates: an item in 2026 has no
    counterpart in 2025 to difference against. The same tickers appear in both,
    which is what makes the comparison a statement about time rather than about
    composition — the reason the same-ticker constraint was structural in selection.
    """
    clean = np.asarray(clean_scores, dtype=np.float64)
    ambiguous = np.asarray(ambiguous_scores, dtype=np.float64)
    if clean.size == 0 or ambiguous.size == 0:
        raise AggregationError("both bands need scored items to estimate leakage")

    rng = np.random.default_rng(seed)
    diffs = np.empty(draws, dtype=np.float64)
    for i in range(draws):
        a = rng.choice(clean, size=clean.size, replace=True)
        b = rng.choice(ambiguous, size=ambiguous.size, replace=True)
        diffs[i] = float(np.mean(a) - np.mean(b))
    tail = (1.0 - confidence) / 2.0 * 100.0
    lower, upper = np.percentile(diffs, [tail, 100.0 - tail])
    return LeakageEstimate(
        clean_mean=float(np.mean(clean)),
        ambiguous_mean=float(np.mean(ambiguous)),
        difference=float(np.mean(clean) - np.mean(ambiguous)),
        lower=float(lower),
        upper=float(upper),
        clean_n=int(clean.size),
        ambiguous_n=int(ambiguous.size),
    )


def calibration_ratio(stated_sigma: Floats, realised: Floats) -> float:
    """Stated dispersion over realised dispersion — the `k` of ADR 0018.

    Below one is overconfident, above one too wide. Computed as a ratio of
    root-mean-square values so a single wild outcome cannot drag it the way a
    variance ratio would.
    """
    stated = np.asarray(stated_sigma, dtype=np.float64)
    actual = np.asarray(realised, dtype=np.float64)
    if stated.size != actual.size:
        raise AggregationError("stated and realised series differ in length")
    if stated.size == 0:
        raise AggregationError("calibration ratio needs at least one item")
    rms_actual = float(np.sqrt(np.mean(actual**2)))
    if rms_actual <= 0.0:
        raise AggregationError("realised outcomes are all zero; ratio is undefined")
    return float(np.sqrt(np.mean(stated**2))) / rms_actual


def summarise(comparisons: Sequence[Comparison]) -> tuple[str, ...]:
    """One reportable line per comparison, power-honest by construction.

    An indistinguishable result is labelled with its sample rather than as "no
    difference", because those are not the same claim.
    """
    lines: list[str] = []
    for c in comparisons:
        if c.significant:
            lines.append(
                f"{c.name} vs {c.baseline}: {c.verdict} by "
                f"{abs(c.relative_improvement):.1%} "
                f"[{c.lower:+.5f}, {c.upper:+.5f}], n={c.n}, "
                f"{c.date_clusters} date clusters"
            )
        else:
            lines.append(
                f"{c.name} vs {c.baseline}: indistinguishable at n={c.n} "
                f"({c.date_clusters} date clusters), "
                f"interval [{c.lower:+.5f}, {c.upper:+.5f}] spans zero — "
                f"this is not evidence of no difference"
            )
    return tuple(lines)
