"""Volatility compression: the estimator records 6, 8 and 9 registered.

The estimator was fixed in git notes and first run from a scratch script that no
longer exists; the figures it produced were written into STATE.md and deleted the
next day (Findings #66). These tests pin the estimator itself, so it cannot be lost
the same way twice.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from mapf.eval.aggregate import AggregationError
from mapf.eval.compression import (
    CUT_FRACTIONS,
    Compression,
    MoveCut,
    compression_interval,
    cut_size,
    largest_move_cuts,
    monotone,
    slope,
)


def _ids(days: object) -> list[str]:
    """One fixed id per item, in position order: the bootstrap orders items that
    share a day by these (Findings #70)."""
    return [f"item{k:05d}" for k in range(len(days))]  # type: ignore[arg-type]


def _days(n: int) -> list[int]:
    # Three items a day over a calendar long enough to occupy many ten-day blocks.
    return [i // 3 for i in range(n)]


def _panel(
    rng: np.random.Generator,
    n: int,
    *,
    true_slope: float,
    base_noise: float,
    map_noise: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """σ(M.A.P.), σ(baseline) and σ(reference) around one true log volatility.

    Both baselines see the truth with independent error of the same size, which is
    the assumption under which their correlation is the baseline's reliability.
    """
    truth = rng.normal(np.log(0.04), 0.4, n)
    base = truth + rng.normal(0.0, base_noise, n)
    reference = truth + rng.normal(0.0, base_noise, n)
    model = true_slope * truth + rng.normal(0.0, map_noise, n)
    return np.exp(model), np.exp(base), np.exp(reference)


def test_an_exact_compression_is_read_the_same_from_both_sides() -> None:
    """No noise anywhere: the forward and inverse reverse slopes coincide, the
    Frisch bounds collapse to the true slope, and λ is one."""
    base = np.exp(np.linspace(np.log(0.01), np.log(0.1), 60))
    model = np.exp(0.4 * np.log(base) - 1.0)
    result = compression_interval(
        model, base, _days(60), reference_sigma=base, draws=50, item_ids=_ids(_days(60))
    )
    assert result.forward == pytest.approx(0.4)
    assert result.inverse_reverse == pytest.approx(0.4)
    assert result.reliability == pytest.approx(1.0)
    assert result.corrected == pytest.approx(0.4)
    assert result.spread_ratio == pytest.approx(0.4)
    assert result.verdict == "compressed"


def test_error_in_the_baseline_attenuates_and_the_correction_undoes_it() -> None:
    """Why record 8 replaced the raw slope. With a reliability of 0.8 the forward
    slope lands near 0.32 when the truth is 0.4 — the development number, reached
    by attenuation alone — and dividing by λ recovers the truth."""
    rng = np.random.default_rng(201)
    model, base, reference = _panel(rng, 6000, true_slope=0.4, base_noise=0.2, map_noise=0.05)
    result = compression_interval(
        model, base, _days(6000), reference_sigma=reference, draws=100, item_ids=_ids(_days(6000))
    )
    assert result.forward == pytest.approx(0.32, abs=0.02)
    assert result.reliability == pytest.approx(0.8, abs=0.02)
    assert result.corrected == pytest.approx(0.4, abs=0.02)
    # The truth lies inside the Frisch bounds, which is what makes them bounds.
    assert result.frisch[0] < 0.4 < result.frisch[1]


def test_a_correctly_spread_model_is_not_called_compressed() -> None:
    """Slope 1.0 with noise on both sides: the forward slope falls below 1 and the
    inverse reverse rises above it, and the widest interval covers 1.0."""
    rng = np.random.default_rng(202)
    model, base, reference = _panel(rng, 600, true_slope=1.0, base_noise=0.2, map_noise=0.2)
    result = compression_interval(
        model, base, _days(600), reference_sigma=reference, draws=300, item_ids=_ids(_days(600))
    )
    assert result.forward < 1.0 < result.inverse_reverse
    assert result.widest[0] < 1.0 < result.widest[1]
    assert result.verdict == "indistinguishable from a slope of 1.0"


def test_the_verdict_reads_the_widest_interval_and_not_the_corrected_one() -> None:
    """GARCH on development, record 9: the corrected interval excludes 1.0 but the
    widest does not, and the registered criterion is the widest."""
    garch_on_development = Compression(
        forward=0.2119,
        forward_ci=(0.1375, 0.2933),
        inverse_reverse=0.9796,
        inverse_reverse_ci=(0.8014, 1.2348),
        reliability=0.8410,
        reliability_ci=(0.7642, 0.8959),
        corrected=0.2520,
        corrected_ci=(0.1656, 0.3423),
        spread_ratio=0.4556,
        n=178,
        date_clusters=18,
    )
    assert garch_on_development.corrected_ci[1] < 1.0
    assert garch_on_development.frisch == (0.2119, 0.9796)
    assert garch_on_development.widest == (0.1375, 1.2348)
    assert garch_on_development.verdict == "indistinguishable from a slope of 1.0"


def test_a_model_spread_wider_than_the_baseline_is_named_as_such() -> None:
    over = Compression(
        forward=1.6,
        forward_ci=(1.4, 1.8),
        inverse_reverse=1.9,
        inverse_reverse_ci=(1.7, 2.2),
        reliability=0.9,
        reliability_ci=(0.85, 0.95),
        corrected=1.78,
        corrected_ci=(1.5, 2.0),
        spread_ratio=1.7,
        n=100,
        date_clusters=10,
    )
    assert over.verdict == "over-spread"


def test_lambda_is_one_number_whichever_baseline_is_regressed_on() -> None:
    rng = np.random.default_rng(203)
    model, base, reference = _panel(rng, 300, true_slope=0.4, base_noise=0.2)
    days = _days(300)
    one = compression_interval(
        model, base, days, reference_sigma=reference, draws=50, item_ids=_ids(days)
    )
    other = compression_interval(
        model, reference, days, reference_sigma=base, draws=50, item_ids=_ids(days)
    )
    assert one.reliability == other.reliability


def test_lambda_is_re_estimated_in_every_resample() -> None:
    """The one choice the registration left open, settled by the record: only a λ
    re-estimated per resample reproduces record 8's development interval. Held at
    its point value, the corrected interval would be the forward one scaled."""
    rng = np.random.default_rng(204)
    model, base, reference = _panel(rng, 300, true_slope=0.4, base_noise=0.2, map_noise=0.05)
    result = compression_interval(
        model, base, _days(300), reference_sigma=reference, draws=300, item_ids=_ids(_days(300))
    )
    scaled = tuple(bound / result.reliability for bound in result.forward_ci)
    assert result.corrected_ci != pytest.approx(scaled, abs=1e-4)
    assert result.reliability_ci[0] < result.reliability < result.reliability_ci[1]


def test_the_interval_is_reproducible_from_the_registered_seed() -> None:
    rng = np.random.default_rng(205)
    model, base, reference = _panel(rng, 240, true_slope=0.4, base_noise=0.2)
    days = _days(240)
    first = compression_interval(
        model, base, days, reference_sigma=reference, draws=200, item_ids=_ids(days)
    )
    again = compression_interval(
        model, base, days, reference_sigma=reference, draws=200, item_ids=_ids(days)
    )
    moved = compression_interval(
        model, base, days, reference_sigma=reference, draws=200, seed=1, item_ids=_ids(days)
    )
    assert first == again
    assert moved.corrected_ci != first.corrected_ci


def test_the_registered_defaults_are_the_ones_in_the_note() -> None:
    defaults = inspect.signature(compression_interval).parameters
    assert defaults["draws"].default == 4000
    assert defaults["seed"].default == 20260813
    assert defaults["horizon_days"].default == 5
    assert defaults["confidence"].default == 0.95


def test_the_block_count_uses_the_same_convention_as_the_rest() -> None:
    result = compression_interval(
        [0.02, 0.03, 0.05, 0.04],
        [0.01, 0.03, 0.06, 0.05],
        [0, 3, 11, 12],
        reference_sigma=[0.012, 0.028, 0.055, 0.052],
        draws=20,
        item_ids=_ids([0, 3, 11, 12]),
    )
    assert result.date_clusters == 2
    assert result.n == 4


def test_mismatched_inputs_refuse() -> None:
    with pytest.raises(AggregationError, match="disagree in length"):
        compression_interval(
            [0.1, 0.2, 0.3],
            [0.1, 0.2, 0.3],
            [0, 1],
            reference_sigma=[0.1, 0.2, 0.3],
            item_ids=_ids([0, 1]),
        )


@pytest.mark.parametrize("bad", [0.0, -0.1, float("nan"), float("inf")])
def test_a_sigma_that_is_not_finite_and_positive_refuses(bad: float) -> None:
    """A σ of zero claims certainty and its log is minus infinity; it would decide
    any regression it entered."""
    with pytest.raises(AggregationError, match="finite and positive"):
        compression_interval(
            [0.1, bad, 0.3],
            [0.1, 0.2, 0.3],
            [0, 1, 2],
            reference_sigma=[0.1, 0.2, 0.3],
            item_ids=_ids([0, 1, 2]),
        )


def test_too_few_items_refuse() -> None:
    with pytest.raises(AggregationError, match="at least three"):
        compression_interval(
            [0.1, 0.2], [0.1, 0.2], [0, 1], reference_sigma=[0.1, 0.2], item_ids=_ids([0, 1])
        )


def test_a_baseline_that_does_not_vary_has_no_slope() -> None:
    with pytest.raises(AggregationError, match="does not vary"):
        slope(np.zeros(5), np.arange(5.0))


def test_a_model_that_does_not_vary_has_no_reverse_slope() -> None:
    with pytest.raises(AggregationError, match="does not vary"):
        compression_interval(
            [0.2, 0.2, 0.2],
            [0.1, 0.2, 0.3],
            [0, 1, 2],
            reference_sigma=[0.1, 0.2, 0.3],
            item_ids=_ids([0, 1, 2]),
        )


def test_a_zero_reverse_slope_refuses_rather_than_dividing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero exactly when the two σ series do not co-vary at all. Driven directly,
    because a float covariance of exactly zero is not something a real panel gives;
    without the guard it would surface as a bare ZeroDivisionError."""
    monkeypatch.setattr("mapf.eval.compression.slope", lambda x, y: 0.0)
    with pytest.raises(AggregationError, match="reverse slope is zero"):
        compression_interval(
            [0.1, 0.2, 0.3],
            [0.1, 0.2, 0.3],
            [0, 1, 2],
            reference_sigma=[0.1, 0.2, 0.3],
            item_ids=_ids([0, 1, 2]),
        )


def test_baselines_that_do_not_agree_give_no_reliability() -> None:
    """Two fits of one volatility that correlate negatively measure nothing in common;
    dividing by that correlation would flip the slope's sign and call it a correction."""
    with pytest.raises(AggregationError, match="not positive"):
        compression_interval(
            [0.1, 0.2, 0.3, 0.4],
            [0.1, 0.2, 0.3, 0.4],
            [0, 1, 2, 3],
            reference_sigma=[0.4, 0.3, 0.2, 0.1],
            item_ids=_ids([0, 1, 2, 3]),
        )


def test_an_interval_with_no_surviving_draw_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """The panel has defined slopes; the one item the sampler is made to pick does
    not. Driven directly for the same reason as the tail ratio's version."""
    monkeypatch.setattr(
        "mapf.eval.compression.block_resamples",
        lambda *a, **k: iter([np.zeros(4, dtype=np.int64)] * 5),
    )
    with pytest.raises(AggregationError, match="no bootstrap resample"):
        compression_interval(
            [0.1, 0.2, 0.3, 0.5],
            [0.1, 0.25, 0.3, 0.4],
            [0, 1, 2, 3],
            reference_sigma=[0.12, 0.2, 0.35, 0.4],
            draws=5,
            item_ids=_ids([0, 1, 2, 3]),
        )


# --- S3: where the narrowness sits ---------------------------------------------


def _moves(
    rng: np.random.Generator, n: int, *, true_slope: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A panel whose realised moves are drawn at each name's true volatility."""
    truth = rng.normal(np.log(0.04), 0.5, n)
    base = truth + rng.normal(0.0, 0.1, n)
    model = true_slope * truth + (1.0 - true_slope) * np.log(0.04)
    moves = rng.normal(0.0, 1.0, n) * np.exp(truth)
    return np.exp(model), np.exp(base), moves


def test_the_cut_sizes_are_developments_counts_as_fractions() -> None:
    """Record 6 expressed 11, 18 and 36 of 178 as 6%, 10% and 20%."""
    assert CUT_FRACTIONS == (0.06, 0.10, 0.20)
    assert [cut_size(f, 178) for f in CUT_FRACTIONS] == [11, 18, 36]
    assert [cut_size(f, 177) for f in CUT_FRACTIONS] == [11, 18, 35]
    assert cut_size(0.5, 5) == 3


def test_a_compressed_model_is_narrowest_on_the_largest_moves() -> None:
    """The prediction record 6 registered: every cut negative, excluding zero, and
    deeper cuts more negative."""
    rng = np.random.default_rng(301)
    model, base, moves = _moves(rng, 900, true_slope=0.3)
    cuts = largest_move_cuts(model, base, moves, _days(900), draws=300, item_ids=_ids(_days(900)))
    assert [c.k for c in cuts] == [54, 90, 180]
    for cut in cuts:
        assert cut.difference < 0.0
        assert cut.upper < 0.0
        assert cut.top_median < cut.rest_median
    assert monotone(cuts)


def test_a_well_spread_model_shows_no_contrast() -> None:
    rng = np.random.default_rng(302)
    model, base, moves = _moves(rng, 900, true_slope=1.0)
    cuts = largest_move_cuts(model, base, moves, _days(900), draws=300, item_ids=_ids(_days(900)))
    assert any(c.lower < 0.0 < c.upper for c in cuts)


def test_membership_is_chosen_once_on_the_whole_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Record 5's intervals reproduce only this way. The resample here draws item 0
    twice and items 3 and 4 once. Items 0 and 1 are the top two of the whole panel, so
    the top side is item 0 twice even though, among what was drawn, item 3 has the
    second-largest move. Re-choosing inside the resample would have taken item 3."""
    sigma_map = [0.1, 0.2, 0.3, 0.4, 0.5]
    sigma_base = [1.0, 1.0, 1.0, 1.0, 1.0]
    moves = [0.09, 0.08, 0.01, 0.05, 0.02]
    drawn = np.array([0, 0, 3, 4, 3])
    monkeypatch.setattr("mapf.eval.compression.block_resamples", lambda *a, **k: iter([drawn] * 3))
    (cut,) = largest_move_cuts(
        sigma_map,
        sigma_base,
        moves,
        [0, 1, 2, 3, 4],
        fractions=(0.4,),
        draws=3,
        item_ids=_ids([0, 1, 2, 3, 4]),
    )
    assert cut.k == 2
    assert (cut.top_median, cut.rest_median) == pytest.approx((0.15, 0.4))
    # Top side drawn: item 0 twice → 0.1. Rest drawn: items 3, 4, 3 → median 0.4.
    assert (cut.lower, cut.upper) == pytest.approx((0.1 - 0.4, 0.1 - 0.4))


def test_each_cut_starts_from_the_seed_afresh() -> None:
    """Also what reproduces record 5: asking for one cut alone gives the interval it
    has among three."""
    rng = np.random.default_rng(303)
    model, base, moves = _moves(rng, 300, true_slope=0.3)
    days = _days(300)
    together = largest_move_cuts(model, base, moves, days, draws=200, item_ids=_ids(days))
    alone = largest_move_cuts(
        model, base, moves, days, fractions=(0.20,), draws=200, item_ids=_ids(days)
    )
    assert alone[0] == together[2]


def test_the_registered_defaults_for_the_cuts() -> None:
    defaults = inspect.signature(largest_move_cuts).parameters
    assert defaults["draws"].default == 4000
    assert defaults["seed"].default == 20260813
    assert defaults["fractions"].default == CUT_FRACTIONS


def test_monotone_reads_the_differences_by_depth() -> None:
    def cut(fraction: float, difference: float) -> MoveCut:
        return MoveCut(fraction, 1, 0.5, 0.5 - difference, difference, -1.0, 0.0)

    assert monotone((cut(0.20, -0.29), cut(0.06, -0.39), cut(0.10, -0.33)))
    # GARCH on development: 6% and 10% within a thousandth, the wrong way round.
    assert not monotone((cut(0.06, -0.2742), cut(0.10, -0.2745), cut(0.20, -0.2388)))


def test_a_cut_with_nothing_either_side_refuses() -> None:
    with pytest.raises(AggregationError, match="leaving no contrast"):
        largest_move_cuts(
            [0.1, 0.2, 0.3], [0.1, 0.2, 0.3], [0.1, 0.2, 0.3], [0, 1, 2], item_ids=_ids([0, 1, 2])
        )
    with pytest.raises(AggregationError, match="leaving no contrast"):
        largest_move_cuts(
            [0.1, 0.2, 0.3],
            [0.1, 0.2, 0.3],
            [0.1, 0.2, 0.3],
            [0, 1, 2],
            fractions=(1.0,),
            item_ids=_ids([0, 1, 2]),
        )


def test_mismatched_cut_inputs_refuse() -> None:
    with pytest.raises(AggregationError, match="cut inputs disagree"):
        largest_move_cuts(
            [0.1, 0.2, 0.3], [0.1, 0.2, 0.3], [0.1, 0.2], [0, 1, 2], item_ids=_ids([0, 1, 2])
        )


def test_a_missing_return_refuses() -> None:
    with pytest.raises(AggregationError, match="finite"):
        largest_move_cuts(
            [0.1, 0.2, 0.3],
            [0.1, 0.2, 0.3],
            [0.1, float("nan"), 0.3],
            [0, 1, 2],
            fractions=(0.5,),
            item_ids=_ids([0, 1, 2]),
        )


def test_a_cut_no_resample_can_contrast_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every resample draws only the top item, so no draw has a rest side."""
    monkeypatch.setattr(
        "mapf.eval.compression.block_resamples",
        lambda *a, **k: iter([np.zeros(3, dtype=np.int64)] * 4),
    )
    with pytest.raises(AggregationError, match="drew both sides"):
        largest_move_cuts(
            [0.1, 0.2, 0.3],
            [0.1, 0.2, 0.3],
            [0.9, 0.2, 0.3],
            [0, 1, 2],
            fractions=(0.3,),
            draws=4,
            item_ids=_ids([0, 1, 2]),
        )


def test_equal_moves_enter_the_cut_in_id_order_not_arrival_order() -> None:
    """Two items with the same |return| straddle the cut. Which one is in it is
    decided by id, so reversing the rows cannot change the cut."""
    sigma_map = [0.1, 0.2, 0.3, 0.4, 0.5]
    sigma_base = [1.0] * 5
    moves = [0.09, 0.05, 0.05, 0.01, 0.02]  # items 1 and 2 tie for second place
    ids = ["a", "c", "b", "d", "e"]
    days = [0, 1, 2, 3, 4]
    (cut,) = largest_move_cuts(
        sigma_map, sigma_base, moves, days, item_ids=ids, fractions=(0.4,), draws=5
    )
    (flipped,) = largest_move_cuts(
        sigma_map[::-1],
        sigma_base,
        moves[::-1],
        days[::-1],
        item_ids=ids[::-1],
        fractions=(0.4,),
        draws=5,
    )
    # "a" (0.09) and "b" (0.05, id before "c") make the cut: sigmas 0.1 and 0.3.
    assert cut.top_median == pytest.approx(0.2)
    assert flipped.top_median == pytest.approx(0.2)
