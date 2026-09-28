"""Aggregation: per-item scores into reportable numbers.

Every assertion here guards a version of the same failure — an interval that comes
out too narrow, or a null read as evidence of no effect.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from mapf.eval.aggregate import (
    AD_FIVE_PERCENT,
    AggregationError,
    Calibration,
    PitTest,
    TailRatio,
    anderson_darling_uniform,
    calibration_interval,
    calibration_ratio,
    compare,
    leakage,
    mad_scale,
    pit_histogram,
    pit_uniformity,
    summarise,
    tail_ratio,
    tail_ratio_interval,
    z_from_pit,
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


# The PIT tilt and shape tests


def test_a_uniform_pit_is_not_called_tilted() -> None:
    rng = np.random.default_rng(3)
    values = rng.uniform(0.0, 1.0, 400)
    result = pit_uniformity(values, _clustered_days(400))
    assert result.tilted == "not established"
    assert result.lower <= 0.5 <= result.upper


def test_a_strong_tilt_is_established_on_both_views() -> None:
    """Shifted well away from 0.5: both the item-level and the cluster-level
    interval must exclude it, or the verdict understates what is there."""
    rng = np.random.default_rng(4)
    values = rng.uniform(0.0, 1.0, 400) * 0.5 + 0.5
    result = pit_uniformity(values, _clustered_days(400))
    assert result.tilted == "established"
    assert result.lower > 0.5
    assert result.cluster_lower > 0.5
    assert result.direction == "outcomes above the forecast centre"


def test_a_tilt_only_one_view_finds_is_suggestive_not_established() -> None:
    """Established requires BOTH. Letting the narrower interval decide would let the
    view whose assumptions do more work carry the claim on its own."""
    wide = PitTest(
        mean=0.55,
        lower=0.51,
        upper=0.59,
        n=178,
        clusters=18,
        cluster_lower=0.49,
        cluster_upper=0.61,
        ks_statistic=0.08,
        ks_p_independent=0.2,
        anderson_darling=1.0,
    )
    assert wide.tilted == "suggestive"


def test_a_symmetric_u_has_no_tilt_and_the_shape_test_still_sees_it() -> None:
    """Why both statistics exist: a U-shaped PIT has a mean of exactly 0.5, so the
    tilt test is silent and only KS reports the departure."""
    values = np.array([0.02, 0.98] * 100)
    result = pit_uniformity(values, _clustered_days(200))
    assert result.tilted == "not established"
    assert result.ks_statistic > 0.3


def test_the_pit_test_refuses_mismatched_inputs() -> None:
    with pytest.raises(AggregationError, match="differ in length"):
        pit_uniformity([0.1, 0.2], [0])


def test_the_pit_test_refuses_an_empty_panel() -> None:
    with pytest.raises(AggregationError, match="at least one item"):
        pit_uniformity([], [])


def test_anderson_darling_is_small_for_a_uniform_sample() -> None:
    rng = np.random.default_rng(7)
    assert anderson_darling_uniform(rng.uniform(0.0, 1.0, 500)) < AD_FIVE_PERCENT


def test_anderson_darling_catches_the_tails_that_ks_misses() -> None:
    """The reason both are reported. A sample right in the body and heavy at the
    ends is the signature of a mis-scaled forecast, and KS is not built to see it."""
    rng = np.random.default_rng(8)
    body = rng.uniform(0.25, 0.75, 180)
    tails = np.concatenate([rng.uniform(0.0, 0.02, 10), rng.uniform(0.98, 1.0, 10)])
    values = np.concatenate([body, tails])
    result = pit_uniformity(values, _clustered_days(200))
    assert result.anderson_darling > AD_FIVE_PERCENT
    assert result.tails_heavy
    assert result.tilted == "not established"


def test_pit_values_at_the_boundary_do_not_make_the_statistic_infinite() -> None:
    """0.0 and 1.0 are legitimate PIT values -- an outcome outside every simulated
    path -- and they are exactly the ones this statistic weighs most."""
    values = [0.0, 1.0, *[i / 20 for i in range(1, 20)]]
    assert math.isfinite(anderson_darling_uniform(values))


def test_anderson_darling_refuses_an_empty_sample() -> None:
    with pytest.raises(AggregationError, match="at least one item"):
        anderson_darling_uniform([])


# --- the tail ratio: RMS(z) over MAD-scale(z) ----------------------------------
#
# Pre-registered in the git note on ad71b13, record 2, before any ambiguous-band
# number existed. These tests guard the two things a later reader could quietly
# change and still get a plausible number out: which centring the MAD uses, and
# whether the verdict is read off the interval or off the point estimate.


def _heavy(rng: np.random.Generator, n: int) -> np.ndarray:
    """A normal mixture: a body plus a rare wide component. Heavier tails than
    Gaussian with the body's scale left alone, which is exactly the shape the ratio
    is supposed to be sensitive to."""
    wide = rng.random(n) < 0.05
    return np.where(wide, rng.normal(0.0, 5.0, n), rng.normal(0.0, 1.0, n))


def test_a_gaussian_sample_has_a_tail_ratio_near_one() -> None:
    rng = np.random.default_rng(101)
    assert 0.9 < tail_ratio(rng.normal(0.0, 1.0, 4000)) < 1.1


def test_a_heavy_tailed_sample_has_a_ratio_above_one() -> None:
    rng = np.random.default_rng(102)
    assert tail_ratio(_heavy(rng, 4000)) > 1.3


def test_the_ratio_is_scale_invariant() -> None:
    """The load-bearing property, and the reason ADR 0033 could predict in advance
    that the calibration correction would not move this number: RMS and MAD-scale
    both divide by any common factor, so `z -> z / b` leaves the ratio alone."""
    rng = np.random.default_rng(103)
    z = _heavy(rng, 500)
    assert tail_ratio(z) == pytest.approx(tail_ratio(z * 7.5), rel=1e-12)
    assert tail_ratio(z) == pytest.approx(tail_ratio(z / 1.3305), rel=1e-12)


def test_mad_scale_is_centred_on_the_median_not_on_zero() -> None:
    """Centring is a choice the pre-registration did not spell out, and it is settled
    by the record: median-centring is what reproduces ADR 0032's 1.0864. A series
    with a deliberate offset makes the two answers differ, so a change of centring
    cannot pass this suite quietly."""
    z = np.array([4.0, 5.0, 6.0, 7.0, 8.0])
    assert mad_scale(z) == pytest.approx(1.4826 * 1.0)
    about_zero = 1.4826 * float(np.median(np.abs(z)))
    assert about_zero == pytest.approx(1.4826 * 6.0)
    assert mad_scale(z) != pytest.approx(about_zero)


def test_mad_scale_recovers_sigma_for_a_gaussian() -> None:
    rng = np.random.default_rng(104)
    assert mad_scale(rng.normal(0.0, 3.0, 20000)) == pytest.approx(3.0, rel=0.05)


def test_a_degenerate_body_refuses_rather_than_dividing_by_zero() -> None:
    with pytest.raises(AggregationError, match="MAD-scale is zero"):
        tail_ratio([0.0, 0.0, 0.0, 0.0, 9.0])


def test_the_mad_scale_needs_data() -> None:
    with pytest.raises(AggregationError, match="at least one item"):
        mad_scale([])


def test_z_from_pit_is_the_inverse_normal_and_not_the_other_definition() -> None:
    """`realised / sigma` is a different statistic, not a different route to this
    one -- it drops the forecast's own centre. The front end pins the gap between
    them; this is the Python side of the same guard."""
    assert z_from_pit([0.5])[0] == pytest.approx(0.0)
    assert z_from_pit([0.975])[0] == pytest.approx(1.959964, abs=1e-6)
    assert z_from_pit([0.025])[0] == pytest.approx(-1.959964, abs=1e-6)


def test_a_pit_of_exactly_zero_or_one_refuses_rather_than_clipping() -> None:
    """Clipping would invent a largest-possible outcome, and the tail statistics are
    precisely what a reader would then take off it."""
    with pytest.raises(AggregationError, match="not finite"):
        z_from_pit([0.4, 1.0])
    with pytest.raises(AggregationError, match="not finite"):
        z_from_pit([0.0, 0.6])


def test_z_from_pit_needs_data() -> None:
    with pytest.raises(AggregationError, match="at least one PIT"):
        z_from_pit([])


def test_the_tail_interval_finds_a_known_heavy_tail() -> None:
    rng = np.random.default_rng(105)
    result = tail_ratio_interval(_heavy(rng, 600), _clustered_days(600), draws=400)
    assert result.ratio > 1.3
    assert result.lower > 1.0
    assert result.verdict == "heavier-tailed than normal"
    assert result.n == 600


def test_a_gaussian_panel_is_not_called_heavy_tailed() -> None:
    rng = np.random.default_rng(106)
    result = tail_ratio_interval(rng.normal(0.0, 1.0, 600), _clustered_days(600), draws=400)
    assert result.lower <= 1.0 <= result.upper
    assert result.verdict == "indistinguishable from normal-tailed"


def test_the_tail_verdict_reads_the_interval_and_not_the_point() -> None:
    """The pre-registered bar is the interval excluding 1.0. A ratio of 1.25 whose
    lower bound reaches 0.9945 is the actual recorded outcome on the ambiguous band,
    and it is undetermined rather than heavy."""
    near = TailRatio(ratio=1.2493, lower=0.9945, upper=1.5365, n=174, date_clusters=24)
    assert near.verdict == "indistinguishable from normal-tailed"
    clear = TailRatio(ratio=1.2064, lower=1.0135, upper=1.4372, n=178, date_clusters=24)
    assert clear.verdict == "heavier-tailed than normal"
    light = TailRatio(ratio=0.9, lower=0.7, upper=0.98, n=50, date_clusters=8)
    assert light.verdict == "lighter-tailed than normal"


def test_the_tail_interval_is_reproducible_from_the_registered_seed() -> None:
    """The seed, the draws and the ten-day blocks are the pre-registration, not
    defaults chosen for convenience. Two calls must agree to the digit."""
    rng = np.random.default_rng(107)
    z = _heavy(rng, 300)
    days = _clustered_days(300)
    first = tail_ratio_interval(z, days, draws=200)
    again = tail_ratio_interval(z, days, draws=200)
    assert (first.lower, first.upper) == (again.lower, again.upper)


def test_the_registered_defaults_are_the_ones_in_the_note() -> None:
    import inspect

    defaults = inspect.signature(tail_ratio_interval).parameters
    assert defaults["draws"].default == 4000
    assert defaults["seed"].default == 20260813
    assert defaults["horizon_days"].default == 5
    assert defaults["method"].default == "percentile"


def test_a_tail_concentrated_in_time_gets_the_wider_interval() -> None:
    """Why the bootstrap is clustered on dates at all. Both panels here hold the same
    240 z, the same twelve extreme values and the same occupied days; only WHEN the
    extremes fall differs. Concentrated in one ten-day block they are effectively one
    observation, because a block resample takes them all or none, and the interval
    has to say so. The naive version of this test -- grouping i.i.d. draws -- proves
    nothing, since grouping alone does not inflate variance."""
    rng = np.random.default_rng(108)
    days = [i // 10 * 10 for i in range(240)]
    base = rng.normal(0.0, 1.0, 240)
    extremes = rng.normal(0.0, 6.0, 12)

    concentrated = base.copy()
    concentrated[:12] = extremes
    spread_out = base.copy()
    spread_out[[i * 20 for i in range(12)]] = extremes

    together = tail_ratio_interval(concentrated, days, draws=800)
    apart = tail_ratio_interval(spread_out, days, draws=800)

    assert together.date_clusters == apart.date_clusters == 24
    assert (together.upper - together.lower) > (apart.upper - apart.lower)
    # And the consequence that matters: the same tail, concentrated, stops clearing
    # the bar by nearly as much.
    assert together.lower < apart.lower


def test_the_block_count_is_reported_on_the_same_convention_as_the_rest() -> None:
    result = tail_ratio_interval([1.0, -2.0, 0.5, 3.0], [0, 3, 11, 12], draws=50)
    assert result.date_clusters == 2


def test_the_basic_interval_is_available_and_reflects_the_draws() -> None:
    """Offered because the pre-registration fixed the resampling and not the interval
    construction, and a bound within 0.006 of the bar should not rest on an
    unexamined convention."""
    rng = np.random.default_rng(109)
    z = _heavy(rng, 400)
    days = _clustered_days(400)
    pct = tail_ratio_interval(z, days, draws=300)
    basic = tail_ratio_interval(z, days, draws=300, method="basic")
    assert pct.ratio == basic.ratio
    assert basic.lower == pytest.approx(2 * pct.ratio - pct.upper)
    assert basic.upper == pytest.approx(2 * pct.ratio - pct.lower)


def test_an_unknown_interval_method_refuses() -> None:
    with pytest.raises(AggregationError, match="unknown interval method"):
        tail_ratio_interval([1.0, 2.0], [0, 1], method="bca")


def test_mismatched_tail_inputs_refuse() -> None:
    with pytest.raises(AggregationError, match="disagree in length"):
        tail_ratio_interval([1.0, 2.0], [0])


def test_a_tail_interval_with_no_surviving_draw_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reachable when the panel has a defined ratio but every resample lands on a
    body with no spread. Driven directly, because contriving it through the sampler
    would take a panel so degenerate it would be testing the fixture. It refuses
    rather than reporting an interval built from whichever draws happened to
    survive."""
    # The whole panel has a defined MAD; the ten items the sampler is made to pick
    # do not. That is the only shape in which this branch is reachable.
    z = [0.0] * 10 + [float(i) for i in range(1, 11)]
    assert mad_scale(z) > 0.0
    monkeypatch.setattr(
        "mapf.eval.aggregate.block_resamples",
        lambda *a, **k: iter([np.arange(10)] * 5),
    )
    with pytest.raises(AggregationError, match="no bootstrap resample"):
        tail_ratio_interval(z, list(range(20)), draws=5)
