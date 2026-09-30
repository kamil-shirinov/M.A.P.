"""The per-item scoring pass.

Generated forecasts and generated prices: this cannot run on the real corpus until
the clean band finishes, and it must not need to in order to be trusted.

The assertions concentrate on the ways a scoring pass silently lies — measuring the
outcome against the wrong price, counting trading days as calendar days, dropping
items without saying so, or comparing a model on all items against a baseline on
some of them.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from mapf.core.models import Bar, Forecast, ModelVersions, PriceWindow
from mapf.eval.scorer import (
    EPOCH,
    BandScores,
    ScoredItem,
    SpotDriftError,
    realised_return,
    score_band,
    score_item,
)
from mapf.eval.window import ScoringError, WindowNotClosedError
from tests.conftest import make_scenario_set

HORIZON = 5
DOC_ID = "sha256:" + "a" * 64
START = date(2025, 1, 6)


def _window(closes: list[float], start: date = START, ticker: str = "AAPL") -> PriceWindow:
    """Consecutive trading bars — weekends omitted, as a real series would be."""
    days: list[date] = []
    day = start
    while len(days) < len(closes):
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return PriceWindow(
        ticker=ticker,
        provider="fake",
        adjustment="split_adjusted",
        bars=tuple(
            Bar(date=d, open=c, high=c + 1.0, low=c - 1.0, close=c, volume=1_000)
            for d, c in zip(days, closes, strict=True)
        ),
    )


def _forecast(as_of: date, spot: float, **overrides: object) -> Forecast:
    kwargs: dict[str, object] = {
        "run_id": "0d1b7d3e-6a1e-4d5f-8f4a-9c2b1a0e7f31",
        "ticker": "AAPL",
        "as_of": datetime.combine(as_of, datetime.min.time(), tzinfo=UTC),
        "horizon_days": HORIZON,
        "spot_price": spot,
        "source_doc_ids": (DOC_ID,),
        "model_versions": ModelVersions(intake="a", analyst="b", structuralist="c"),
        "scenarios": make_scenario_set(),
    }
    kwargs.update(overrides)
    return Forecast.model_validate(kwargs)


def _flat(n: int, level: float = 100.0) -> list[float]:
    return [level] * n


# ---------------------------------------------------------------------------
# The realised return
# ---------------------------------------------------------------------------
def test_the_return_is_measured_over_trading_bars_not_calendar_days() -> None:
    """A five-day window spanning a weekend is still five bars."""
    closes = _flat(20)
    closes[5] = 110.0  # the fifth bar after index 0
    window = _window(closes)
    got = realised_return(window, window.bars[0].date, HORIZON, 100.0)
    assert got == pytest.approx(math.log(1.10))


def test_an_as_of_that_is_not_a_trading_day_uses_the_last_bar_before_it() -> None:
    window = _window(_flat(20))
    saturday = window.bars[4].date + timedelta(days=1)
    while saturday.weekday() < 5:
        saturday += timedelta(days=1)
    assert realised_return(window, saturday, HORIZON, 100.0) == pytest.approx(0.0)


def test_a_series_starting_after_the_forecast_is_refused() -> None:
    window = _window(_flat(20), start=date(2026, 1, 5))
    with pytest.raises(ScoringError, match="no bar on or before"):
        realised_return(window, date(2025, 1, 6), HORIZON, 100.0)


def test_an_unclosed_window_is_refused_rather_than_skipped() -> None:
    """Dropping it quietly would shrink the reportable sample invisibly."""
    window = _window(_flat(8))
    with pytest.raises(WindowNotClosedError, match="needs 5 bars"):
        realised_return(window, window.bars[5].date, HORIZON, 100.0)


def test_a_price_series_that_disagrees_with_the_recorded_spot_is_refused() -> None:
    """Vintage drift: the corpus would be scored against a different series than it
    was produced from."""
    window = _window(_flat(20, level=100.0))
    with pytest.raises(SpotDriftError, match="different series"):
        realised_return(window, window.bars[0].date, HORIZON, 95.0)


def test_a_negligible_spot_difference_is_tolerated() -> None:
    window = _window(_flat(20, level=100.0))
    assert realised_return(window, window.bars[0].date, HORIZON, 100.000001) == pytest.approx(
        0.0, abs=1e-6
    )


# ---------------------------------------------------------------------------
# Scoring one item
# ---------------------------------------------------------------------------
def _realistic_window(n: int = 400, seed: int = 0, ticker: str = "AAPL") -> PriceWindow:
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, 0.012, size=n)
    closes = list(100.0 * np.exp(np.cumsum(steps)))
    return _window(closes, ticker=ticker)


def test_an_item_scores_map_and_every_baseline() -> None:
    window = _realistic_window()
    as_of = window.bars[-HORIZON - 1].date
    spot = window.bars[-HORIZON - 1].close
    item = score_item(_forecast(as_of, spot), window, band="clean", paths=4000)
    assert item.map_crps > 0.0
    assert set(item.names) == {"random_walk", "garch", "earnings_scaled_random_walk"}
    assert all(v > 0.0 for v in item.baseline_crps.values())


def test_the_day_index_is_a_calendar_offset_for_clustering() -> None:
    window = _realistic_window()
    as_of = window.bars[-HORIZON - 1].date
    item = score_item(
        _forecast(as_of, window.bars[-HORIZON - 1].close), window, band="clean", paths=500
    )
    assert item.day_index == (as_of - EPOCH).days


def test_data_after_the_window_cannot_change_the_score() -> None:
    """The exact statement of no look-ahead: everything the score depends on lies
    at or before the window's close, so appending a different future must be
    invisible. Asserting on CRPS magnitude instead would not distinguish a leak,
    because CRPS is dominated by the size of the realised move."""
    rng = np.random.default_rng(1)
    shared = list(100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, 320))))
    index = 300

    quiet_tail = list(shared[-1] * np.exp(np.cumsum(np.full(40, 0.0001))))
    shock = np.random.default_rng(2).normal(0, 0.08, 40)
    violent_tail = list(shared[-1] * np.exp(np.cumsum(shock)))
    quiet_window = _window(shared + quiet_tail)
    violent_window = _window(shared + violent_tail)

    as_of = quiet_window.bars[index].date
    spot = quiet_window.bars[index].close
    forecast = _forecast(as_of, spot)

    a = score_item(forecast, quiet_window, band="clean", paths=2000)
    b = score_item(forecast, violent_window, band="clean", paths=2000)
    assert a.realised_return == pytest.approx(b.realised_return)
    assert a.map_crps == pytest.approx(b.map_crps)
    assert a.baseline_crps == pytest.approx(b.baseline_crps)


def test_a_short_history_omits_the_baselines_it_cannot_fit() -> None:
    """Omitted rather than defaulted: a substituted guess would put a number in the
    comparison column that no model produced."""
    window = _realistic_window(n=80)
    as_of = window.bars[-HORIZON - 1].date
    item = score_item(
        _forecast(as_of, window.bars[-HORIZON - 1].close), window, band="clean", paths=500
    )
    assert "random_walk" in item.baseline_crps
    assert "garch" not in item.baseline_crps


def test_a_confident_correct_forecast_scores_better_than_a_wrong_one() -> None:
    """The known answer that makes the whole pass meaningful."""
    closes = _flat(400)
    for i in range(400):
        closes[i] = 100.0 * (1.0 + 0.0001 * i)
    window = _window(closes)
    index = 350
    as_of, spot = window.bars[index].date, window.bars[index].close
    outcome = math.log(window.bars[index + HORIZON].close / spot)

    right = _forecast(
        as_of,
        spot,
        scenarios=make_scenario_set(
            weights=(0.1, 0.8, 0.1),
            modifiers=(0.02, math.expm1(outcome), -0.02),
            vols=(0.10, 0.05, 0.10),
        ),
    )
    wrong = _forecast(
        as_of,
        spot,
        scenarios=make_scenario_set(
            weights=(0.1, 0.8, 0.1), modifiers=(0.30, 0.20, 0.10), vols=(0.10, 0.05, 0.10)
        ),
    )
    a = score_item(right, window, band="clean", paths=8000)
    b = score_item(wrong, window, band="clean", paths=8000)
    assert a.map_crps < b.map_crps


def test_the_pit_value_lands_where_the_outcome_did() -> None:
    closes = _flat(400)
    window = _window(closes)
    index = 350
    as_of, spot = window.bars[index].date, window.bars[index].close
    # Outcome is exactly zero; a forecast centred well above it must read low.
    bullish = _forecast(
        as_of,
        spot,
        scenarios=make_scenario_set(
            weights=(0.1, 0.8, 0.1), modifiers=(0.30, 0.20, 0.10), vols=(0.10, 0.05, 0.10)
        ),
    )
    assert score_item(bullish, window, band="clean", paths=8000).map_pit < 0.05


# ---------------------------------------------------------------------------
# Scoring a band
# ---------------------------------------------------------------------------
def _prices_for(windows: dict[str, PriceWindow]):  # type: ignore[no-untyped-def]
    def fetch(ticker: str, start: date, end: date) -> PriceWindow:
        return windows[ticker]

    return fetch


def test_a_band_scores_every_item_it_can() -> None:
    window = _realistic_window()
    as_of = window.bars[-HORIZON - 1].date
    spot = window.bars[-HORIZON - 1].close
    forecasts = [(_forecast(as_of, spot), "clean")] * 3
    scores = score_band(forecasts, prices=_prices_for({"AAPL": window}), paths=500)
    assert scores.n == 3
    assert scores.unscored == {}


def test_unscorable_items_are_counted_by_reason(caplog: pytest.LogCaptureFixture) -> None:
    """The count is a reportable fact, not a silent shrink."""
    window = _realistic_window()
    good = (_forecast(window.bars[-HORIZON - 1].date, window.bars[-HORIZON - 1].close), "clean")
    open_window = (_forecast(window.bars[-2].date, window.bars[-2].close), "clean")
    drifted = (_forecast(window.bars[10].date, 1.0), "clean")
    scores = score_band(
        [good, open_window, drifted], prices=_prices_for({"AAPL": window}), paths=500
    )
    assert scores.n == 1
    assert scores.unscored["WindowNotClosedError"] == 1
    assert scores.unscored["SpotDriftError"] == 1


def test_pairing_uses_only_items_both_forecasters_scored() -> None:
    """Comparing M.A.P. on all items against a baseline on some would be a
    comparison of two different samples."""
    long_window = _realistic_window(n=400)
    short_window = _realistic_window(n=80, seed=3, ticker="SHRT")
    items = [
        (
            _forecast(long_window.bars[-HORIZON - 1].date, long_window.bars[-HORIZON - 1].close),
            "clean",
        ),
        (
            _forecast(
                short_window.bars[-HORIZON - 1].date,
                short_window.bars[-HORIZON - 1].close,
                ticker="SHRT",
            ),
            "clean",
        ),
    ]
    scores = score_band(
        items,
        prices=_prices_for({"AAPL": long_window, "SHRT": short_window}),
        paths=500,
    )
    assert scores.n == 2
    model, base, days, _ids = scores.paired("garch")
    assert len(model) == len(base) == len(days) == 1
    assert len(scores.crps()) == 2


def test_the_band_exposes_what_aggregation_needs() -> None:
    window = _realistic_window()
    as_of = window.bars[-HORIZON - 1].date
    scores = score_band(
        [(_forecast(as_of, window.bars[-HORIZON - 1].close), "clean")] * 2,
        prices=_prices_for({"AAPL": window}),
        paths=500,
    )
    assert len(scores.day_index) == 2
    assert len(scores.pit_values) == 2
    assert all(0.0 <= v <= 1.0 for v in scores.pit_values)


def test_an_empty_band_is_empty_rather_than_an_error() -> None:
    scores = score_band([], prices=_prices_for({}))
    assert scores == BandScores(items=(), unscored={})
    assert scores.n == 0


def test_earnings_dates_reach_the_scaled_baseline() -> None:
    window = _realistic_window()
    as_of = window.bars[-HORIZON - 1].date
    quarters = [window.bars[i].date for i in range(60, 340, 63)]
    scores = score_band(
        [(_forecast(as_of, window.bars[-HORIZON - 1].close), "clean")],
        prices=_prices_for({"AAPL": window}),
        earnings=lambda _ticker, _as_of: quarters,
        paths=500,
    )
    item = scores.items[0]
    assert "earnings_scaled_random_walk" in item.baseline_crps


def test_crps_can_be_read_for_a_single_baseline() -> None:
    window = _realistic_window()
    as_of = window.bars[-HORIZON - 1].date
    scores = score_band(
        [(_forecast(as_of, window.bars[-HORIZON - 1].close), "clean")] * 2,
        prices=_prices_for({"AAPL": window}),
        paths=500,
    )
    assert len(scores.crps("random_walk")) == 2
    assert scores.crps("random_walk") != scores.crps()


# Direction, and whether the baselines can say anything about it


def _scored(**kw: object) -> ScoredItem:
    base: dict[str, object] = {
        "ticker": "AAA",
        "band": "clean",
        "as_of": date(2026, 1, 5),
        "horizon_days": 5,
        "realised_return": 0.02,
        "day_index": 0,
        "map_crps": 0.01,
        "map_sigma": 0.05,
        "map_pit": 0.5,
        "map_log_score": -1.0,
        "map_brier": 0.09,
        "map_probability_up": 0.7,
        "baseline_crps": {"random_walk": 0.02},
        "baseline_log_score": {"random_walk": -0.9},
        "baseline_brier": {"random_walk": 0.25},
    }
    base.update(kw)
    return ScoredItem(**base)  # type: ignore[arg-type]


def test_zero_drift_baselines_are_reported_as_carrying_no_direction() -> None:
    """All three baselines set mean=0.0, so each scores exactly 0.25 on every item.
    Three identical Brier comparisons would read as three pieces of evidence."""
    scores = BandScores(items=(_scored(), _scored(realised_return=-0.01)), unscored={})
    assert not scores.baselines_carry_direction


def test_a_baseline_with_drift_is_compared_on_its_own() -> None:
    """Checked rather than assumed: a baseline that later gains a drift term must
    go back to being reported separately."""
    scores = BandScores(items=(_scored(baseline_brier={"drifting": 0.16}), _scored()), unscored={})
    assert scores.baselines_carry_direction


def test_a_tie_counts_as_half_a_call_not_a_correct_one() -> None:
    """P(up) of exactly 0.5 claims no direction; scoring it as a hit would inflate
    the accuracy of a model that declined to answer."""
    scores = BandScores(
        items=(_scored(map_probability_up=0.5), _scored(map_probability_up=0.5)),
        unscored={},
    )
    assert scores.directional_hits == 1.0
    assert scores.directional_accuracy == 0.5


def test_directional_accuracy_reads_the_side_not_the_magnitude() -> None:
    right = _scored(map_probability_up=0.51, realised_return=0.9)
    wrong = _scored(map_probability_up=0.99, realised_return=-0.001)
    scores = BandScores(items=(right, wrong), unscored={})
    assert scores.directional_hits == 1.0


def test_conviction_reports_the_span_of_the_directional_claim() -> None:
    items = tuple(_scored(map_probability_up=p) for p in (0.30, 0.50, 0.62))
    low, middle, high = BandScores(items=items, unscored={}).conviction
    assert (low, middle, high) == (0.30, 0.50, 0.62)


def test_conviction_of_an_empty_band_is_not_a_crash() -> None:
    assert BandScores(items=(), unscored={}).conviction == (0.0, 0.0, 0.0)
    assert BandScores(items=(), unscored={}).directional_accuracy == 0.0


def test_the_metric_selector_pairs_the_right_pair_of_fields() -> None:
    """`paired` reaching for map_crps while indexing baseline_log_score would still
    return numbers, and they would be silently meaningless."""
    scores = BandScores(items=(_scored(),), unscored={})
    assert scores.paired("random_walk", "crps")[:2] == ([0.01], [0.02])
    assert scores.paired("random_walk", "log score")[:2] == ([-1.0], [-0.9])
    assert scores.paired("random_walk", "brier")[:2] == ([0.09], [0.25])
    assert scores.scores("log score") == [-1.0]
    assert scores.scores("brier", "random_walk") == [0.25]
