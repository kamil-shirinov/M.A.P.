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
from mapf.eval.compression import Compression, compression_interval, slope


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
    result = compression_interval(model, base, _days(60), reference_sigma=base, draws=50)
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
    result = compression_interval(model, base, _days(6000), reference_sigma=reference, draws=100)
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
    result = compression_interval(model, base, _days(600), reference_sigma=reference, draws=300)
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
    one = compression_interval(model, base, days, reference_sigma=reference, draws=50)
    other = compression_interval(model, reference, days, reference_sigma=base, draws=50)
    assert one.reliability == other.reliability


def test_lambda_is_re_estimated_in_every_resample() -> None:
    """The one choice the registration left open, settled by the record: only a λ
    re-estimated per resample reproduces record 8's development interval. Held at
    its point value, the corrected interval would be the forward one scaled."""
    rng = np.random.default_rng(204)
    model, base, reference = _panel(rng, 300, true_slope=0.4, base_noise=0.2, map_noise=0.05)
    result = compression_interval(model, base, _days(300), reference_sigma=reference, draws=300)
    scaled = tuple(bound / result.reliability for bound in result.forward_ci)
    assert result.corrected_ci != pytest.approx(scaled, abs=1e-4)
    assert result.reliability_ci[0] < result.reliability < result.reliability_ci[1]


def test_the_interval_is_reproducible_from_the_registered_seed() -> None:
    rng = np.random.default_rng(205)
    model, base, reference = _panel(rng, 240, true_slope=0.4, base_noise=0.2)
    days = _days(240)
    first = compression_interval(model, base, days, reference_sigma=reference, draws=200)
    again = compression_interval(model, base, days, reference_sigma=reference, draws=200)
    moved = compression_interval(model, base, days, reference_sigma=reference, draws=200, seed=1)
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
    )
    assert result.date_clusters == 2
    assert result.n == 4


def test_mismatched_inputs_refuse() -> None:
    with pytest.raises(AggregationError, match="disagree in length"):
        compression_interval(
            [0.1, 0.2, 0.3], [0.1, 0.2, 0.3], [0, 1], reference_sigma=[0.1, 0.2, 0.3]
        )


@pytest.mark.parametrize("bad", [0.0, -0.1, float("nan"), float("inf")])
def test_a_sigma_that_is_not_finite_and_positive_refuses(bad: float) -> None:
    """A σ of zero claims certainty and its log is minus infinity; it would decide
    any regression it entered."""
    with pytest.raises(AggregationError, match="finite and positive"):
        compression_interval(
            [0.1, bad, 0.3], [0.1, 0.2, 0.3], [0, 1, 2], reference_sigma=[0.1, 0.2, 0.3]
        )


def test_too_few_items_refuse() -> None:
    with pytest.raises(AggregationError, match="at least three"):
        compression_interval([0.1, 0.2], [0.1, 0.2], [0, 1], reference_sigma=[0.1, 0.2])


def test_a_baseline_that_does_not_vary_has_no_slope() -> None:
    with pytest.raises(AggregationError, match="does not vary"):
        slope(np.zeros(5), np.arange(5.0))


def test_a_model_that_does_not_vary_has_no_reverse_slope() -> None:
    with pytest.raises(AggregationError, match="does not vary"):
        compression_interval(
            [0.2, 0.2, 0.2], [0.1, 0.2, 0.3], [0, 1, 2], reference_sigma=[0.1, 0.2, 0.3]
        )


def test_a_zero_reverse_slope_refuses_rather_than_dividing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero exactly when the two σ series do not co-vary at all. Driven directly,
    because a float covariance of exactly zero is not something a real panel gives;
    without the guard it would surface as a bare ZeroDivisionError."""
    monkeypatch.setattr("mapf.eval.compression.slope", lambda x, y: 0.0)
    with pytest.raises(AggregationError, match="reverse slope is zero"):
        compression_interval(
            [0.1, 0.2, 0.3], [0.1, 0.2, 0.3], [0, 1, 2], reference_sigma=[0.1, 0.2, 0.3]
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
        )
