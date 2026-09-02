"""Aggregation: per-item scores into reportable numbers.

Every assertion here guards a version of the same failure — an interval that comes
out too narrow, or a null read as evidence of no effect.
"""

from __future__ import annotations

import numpy as np
import pytest

from mapf.eval.aggregate import (
    AggregationError,
    Calibration,
    calibration_interval,
    calibration_ratio,
    compare,
    leakage,
    pit_histogram,
    summarise,
)
from mapf.eval.scoring import pit, pit_deviation


def _days(n: int, per_day: int = 1) -> list[int]:
    return [i // per_day for i in range(n)]


# ---------------------------------------------------------------------------
# Paired comparison
# ---------------------------------------------------------------------------
def test_a_uniformly_better_model_is_detected() -> None:
    n = 200
    base = [1.0] * n
    model = [0.8] * n
    result = compare(model, base, _days(n), name="map", baseline="rw")
    assert result.mean_difference == pytest.approx(-0.2)
    assert result.verdict == "better"
    assert result.relative_improvement == pytest.approx(0.2)


def test_a_uniformly_worse_model_is_detected() -> None:
    n = 200
    result = compare([1.3] * n, [1.0] * n, _days(n), name="map", baseline="rw")
    assert result.verdict == "worse"
    assert result.significant is True


def test_identical_forecasters_are_indistinguishable() -> None:
    n = 200
    rng = np.random.default_rng(0)
    scores = rng.normal(1.0, 0.3, size=n)
    result = compare(scores, scores, _days(n), name="a", baseline="b")
    assert result.mean_difference == pytest.approx(0.0)
    assert result.significant is False
    assert result.verdict == "indistinguishable"


def test_pairing_removes_the_common_market_move() -> None:
    """Both forecasters see the same outcome; without pairing the interval would be
    dominated by noise neither of them controls."""
    rng = np.random.default_rng(1)
    n = 300
    common = rng.normal(0.0, 5.0, size=n)  # huge shared component
    model = common + 0.1
    base = common + 0.2
    result = compare(model, base, _days(n), name="map", baseline="rw")
    assert result.mean_difference == pytest.approx(-0.1, abs=1e-9)
    assert result.significant is True
    # The shared component dwarfs the effect; only pairing makes it visible.
    assert np.std(common) > 20 * abs(result.mean_difference)


def test_clustered_dates_widen_the_interval() -> None:
    """Many forecasts on one day are not many independent observations.

    Grouping alone does not inflate variance — 4 groups of 60 independent draws
    have exactly the variance of 240 singletons. What inflates it is *correlation
    within* a cluster, so the scores here carry a shared per-day component, which
    is what a common market move actually is.
    """
    rng = np.random.default_rng(2)
    n, per_day = 240, 60
    group = np.repeat(rng.normal(0.0, 1.0, size=n // per_day), per_day)
    scores = group + rng.normal(0.0, 0.1, size=n)
    zeros = np.zeros(n)

    spread = compare(scores, zeros, list(range(n)), name="m", baseline="b")
    clustered = compare(
        scores, zeros, [(i // per_day) * per_day for i in range(n)], name="m", baseline="b"
    )

    assert clustered.date_clusters < spread.date_clusters
    assert (clustered.upper - clustered.lower) > 2 * (spread.upper - spread.lower)


def test_the_date_cluster_count_is_reported() -> None:
    result = compare([1.0] * 100, [1.1] * 100, _days(100, per_day=25), name="m", baseline="b")
    assert result.date_clusters <= 4
    assert result.n == 100


def test_mismatched_lengths_are_refused() -> None:
    with pytest.raises(AggregationError, match="disagree in length"):
        compare([1.0, 2.0], [1.0], [0, 1], name="m", baseline="b")


def test_an_empty_comparison_is_refused() -> None:
    with pytest.raises(AggregationError, match="no scored items"):
        compare([], [], [], name="m", baseline="b")


def test_non_finite_scores_are_refused() -> None:
    """A NaN would propagate silently into the reported mean."""
    with pytest.raises(AggregationError, match="non-finite"):
        compare([1.0, float("nan")], [1.0, 1.0], [0, 1], name="m", baseline="b")


def test_a_zero_baseline_does_not_divide_by_zero() -> None:
    result = compare([0.0] * 50, [0.0] * 50, _days(50), name="m", baseline="b")
    assert result.relative_improvement == 0.0


# ---------------------------------------------------------------------------
# The report never states a null as a finding
# ---------------------------------------------------------------------------
def test_an_indistinguishable_result_is_not_reported_as_no_difference() -> None:
    rng = np.random.default_rng(3)
    scores = rng.normal(1.0, 0.5, size=120)
    (line,) = summarise([compare(scores, scores, _days(120), name="map", baseline="rw")])
    assert "indistinguishable" in line
    assert "not evidence of no difference" in line
    assert "n=120" in line


def test_a_significant_result_reports_its_direction_and_sample() -> None:
    (line,) = summarise([compare([0.5] * 150, [1.0] * 150, _days(150), name="map", baseline="rw")])
    assert "better" in line
    assert "n=150" in line
    assert "date clusters" in line


# ---------------------------------------------------------------------------
# Leakage
# ---------------------------------------------------------------------------
def test_leakage_is_flagged_when_the_ambiguous_band_scores_better() -> None:
    """Contamination flatters, so a remembered outcome scores lower."""
    rng = np.random.default_rng(4)
    clean = rng.normal(1.0, 0.1, size=300)
    ambiguous = rng.normal(0.7, 0.1, size=300)
    estimate = leakage(clean, ambiguous)
    assert estimate.difference == pytest.approx(0.3, abs=0.05)
    assert estimate.suggests_leakage is True


def test_no_leakage_when_the_bands_agree() -> None:
    rng = np.random.default_rng(5)
    estimate = leakage(rng.normal(1.0, 0.2, size=300), rng.normal(1.0, 0.2, size=300))
    assert estimate.suggests_leakage is False


def test_leakage_records_both_band_sizes() -> None:
    estimate = leakage([1.0] * 40, [0.9] * 30)
    assert (estimate.clean_n, estimate.ambiguous_n) == (40, 30)


def test_leakage_needs_both_bands() -> None:
    with pytest.raises(AggregationError, match="both bands"):
        leakage([1.0], [])


# ---------------------------------------------------------------------------
# The calibration ratio
# ---------------------------------------------------------------------------
def test_a_perfectly_calibrated_forecaster_has_ratio_one() -> None:
    rng = np.random.default_rng(6)
    realised = rng.normal(0.0, 0.04, size=5000)
    assert calibration_ratio([0.04] * 5000, realised) == pytest.approx(1.0, abs=0.05)


def test_an_overconfident_forecaster_has_a_ratio_below_one() -> None:
    rng = np.random.default_rng(7)
    realised = rng.normal(0.0, 0.04, size=5000)
    assert calibration_ratio([0.02] * 5000, realised) == pytest.approx(0.5, abs=0.05)


def test_an_all_zero_outcome_series_is_refused_rather_than_infinite() -> None:
    with pytest.raises(AggregationError, match="undefined"):
        calibration_ratio([0.04] * 10, [0.0] * 10)


def test_the_calibration_ratio_rejects_mismatched_series() -> None:
    with pytest.raises(AggregationError, match="differ in length"):
        calibration_ratio([0.1, 0.2], [0.1])


def test_the_calibration_ratio_needs_data() -> None:
    with pytest.raises(AggregationError, match="at least one"):
        calibration_ratio([], [])


# ---------------------------------------------------------------------------
# PIT — the diagnostic that says which way to move
# ---------------------------------------------------------------------------
def test_pit_is_uniform_for_a_calibrated_forecaster() -> None:
    rng = np.random.default_rng(8)
    y = rng.normal(0.0, 0.04, size=20000)
    values = pit(0.0, 0.04, y)
    assert pit_deviation(values) < 0.02


def test_pit_is_u_shaped_when_intervals_are_too_narrow() -> None:
    """Outcomes land in the tails: the signature of overconfidence."""
    rng = np.random.default_rng(9)
    y = rng.normal(0.0, 0.08, size=20000)
    values = pit(0.0, 0.02, y)
    tails = float(np.mean((values < 0.1) | (values > 0.9)))
    assert tails > 0.5
    assert pit_deviation(values) > 0.2


def test_pit_is_humped_when_intervals_are_too_wide() -> None:
    rng = np.random.default_rng(10)
    y = rng.normal(0.0, 0.02, size=20000)
    values = pit(0.0, 0.08, y)
    middle = float(np.mean((values > 0.4) & (values < 0.6)))
    assert middle > 0.4


def test_pit_leans_when_the_mean_is_biased() -> None:
    rng = np.random.default_rng(11)
    y = rng.normal(0.05, 0.02, size=20000)
    assert float(np.mean(pit(0.0, 0.02, y))) > 0.8


def test_pit_rejects_a_non_positive_sigma() -> None:
    with pytest.raises(ValueError, match="sigma must be positive"):
        pit(0.0, 0.0, 0.1)


def test_pit_deviation_needs_values() -> None:
    with pytest.raises(ValueError, match="at least one"):
        pit_deviation(np.array([]))


def test_pit_deviation_is_zero_for_a_perfect_grid() -> None:
    """The known answer: evenly spaced values are exactly uniform."""
    n = 1000
    grid = (np.arange(n) + 0.5) / n
    assert pit_deviation(grid) == pytest.approx(1.0 / (2 * n), abs=1e-9)


# The calibration interval and the PIT histogram


def _clustered_days(n: int) -> list[int]:
    """Four items per occupied day, a week apart -- the panel's real shape."""
    return [i // 4 * 7 for i in range(n)]


def test_the_calibration_interval_brackets_a_known_ratio() -> None:
    """Sigma stated at exactly twice the realised dispersion must land near 2.0, and
    the interval must exclude 1.0 -- otherwise it cannot say anything at all."""
    rng = np.random.default_rng(11)
    realised = rng.normal(0.0, 0.05, 200)
    stated = np.full(200, 0.10)
    result = calibration_interval(stated, realised, _clustered_days(200))
    assert 1.7 < result.ratio < 2.3
    assert result.lower > 1.0
    assert result.verdict == "over-dispersed"


def test_a_calibrated_forecaster_is_not_called_miscalibrated() -> None:
    rng = np.random.default_rng(12)
    realised = rng.normal(0.0, 0.05, 300)
    stated = np.full(300, float(np.sqrt(np.mean(realised**2))))
    result = calibration_interval(stated, realised, _clustered_days(300))
    assert result.lower <= 1.0 <= result.upper
    assert result.verdict == "indistinguishable from calibrated"


def test_the_verdict_reads_the_interval_and_not_the_point() -> None:
    """The whole reason for the interval: 0.95 is not evidence of miscalibration."""
    near = Calibration(ratio=0.95, lower=0.80, upper=1.10, n=50)
    assert near.verdict == "indistinguishable from calibrated"
    narrow = Calibration(ratio=0.95, lower=0.90, upper=0.99, n=50)
    assert narrow.verdict == "under-dispersed"


def test_mismatched_calibration_inputs_refuse() -> None:
    with pytest.raises(AggregationError, match="disagree in length"):
        calibration_interval([0.1, 0.2], [0.1], [0, 1])


def test_a_flat_pit_histogram_is_flat() -> None:
    # Bin CENTRES, not edges: 0.3 lands in bin 2 or 3 depending on the last bit of
    # the float, and a test that turns on that is testing numpy's rounding.
    counts = pit_histogram([(i + 0.5) / 100 for i in range(100)])
    assert counts == (10,) * 10
    assert sum(counts) == 100


def test_the_pit_histogram_puts_the_edges_in_the_end_bins() -> None:
    """0.0 and 1.0 are legitimate PIT values and must not fall outside the range."""
    counts = pit_histogram([0.0, 1.0, 0.5])
    assert sum(counts) == 3
    assert counts[0] == 1 and counts[-1] == 1


def test_an_empty_pit_histogram_refuses() -> None:
    with pytest.raises(AggregationError, match="at least one item"):
        pit_histogram([])


def test_a_degenerate_resample_is_dropped_and_the_rest_still_report() -> None:
    """Blocks whose outcomes are all exactly zero have no defined ratio. They are
    dropped, not replaced by a guess, and their absence must not stop the interval."""
    realised = [0.0] * 40 + [0.03, -0.02] * 20
    stated = [0.04] * 80
    days = [0] * 40 + [i // 2 * 7 + 70 for i in range(40)]
    result = calibration_interval(stated, realised, days, draws=400)
    assert result.lower < result.upper
    assert result.n == 80


def test_an_all_zero_panel_refuses_on_the_point_estimate() -> None:
    with pytest.raises(AggregationError, match="realised outcomes are all zero"):
        calibration_interval([0.04] * 20, [0.0] * 20, list(range(20)), draws=50)


def test_an_interval_with_no_surviving_draw_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reachable only when the panel has a defined ratio but every resample lands
    on zeros. Driven directly, because contriving it through the sampler would take
    a panel so degenerate it would be testing the fixture."""
    realised = [0.0] * 19 + [0.05]
    monkeypatch.setattr(
        "mapf.eval.aggregate.block_resamples",
        lambda *a, **k: iter([np.arange(19)] * 5),
    )
    with pytest.raises(AggregationError, match="no bootstrap resample"):
        calibration_interval([0.04] * 20, realised, list(range(20)), draws=5)
