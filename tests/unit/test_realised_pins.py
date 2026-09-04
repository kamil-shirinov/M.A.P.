"""The outcome bar is anchored the way the spot is, from first scoring onward."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from mapf.core.models import Forecast, PriceWindow
from mapf.corpus.pins import RealisedPins
from mapf.eval.scorer import (
    RealisedDriftError,
    RealisedPin,
    ScoringError,
    WindowNotClosedError,
    realised_bar,
    score_item,
)
from tests.unit.test_scorer import HORIZON, START, _forecast, _window


def _pins(tmp_path: Path) -> RealisedPins:
    return RealisedPins(tmp_path / "realised_pins.jsonl")


def _item() -> tuple[Forecast, PriceWindow]:
    """One forecast and a series long enough to close its horizon."""
    closes = [100.0 + i for i in range(HORIZON * 3)]
    window = _window(closes)
    forecast = _forecast(START, closes[0])
    return forecast, window


def test_the_first_scoring_takes_the_pin(tmp_path: Path) -> None:
    store = _pins(tmp_path)
    f, w = _item()
    score_item(f, w, band="clean", pin=store.get, record_pin=store.record)

    bar = realised_bar(w, f.as_of.date(), f.horizon_days)
    held = store.get(f.ticker, f.as_of.date(), f.horizon_days)
    assert held is not None
    assert held.realised_date == bar.date
    assert held.realised_close == pytest.approx(bar.close)


def test_scoring_twice_against_the_same_series_validates(tmp_path: Path) -> None:
    """The pin must not fire on its own creation, which is the failure mode of any
    guard that writes what it then checks."""
    store = _pins(tmp_path)
    f, w = _item()
    first = score_item(f, w, band="clean", pin=store.get, record_pin=store.record)
    again = score_item(f, w, band="clean", pin=store.get, record_pin=store.record)
    assert first.realised_return == pytest.approx(again.realised_return)
    assert len(store) == 1


def test_a_changed_realised_close_is_refused(tmp_path: Path) -> None:
    store = _pins(tmp_path)
    f, w = _item()
    score_item(f, w, band="clean", pin=store.get, record_pin=store.record)

    held = store.get(f.ticker, f.as_of.date(), f.horizon_days)
    assert held is not None
    store._pins[held.key] = RealisedPin(  # noqa: SLF001 - simulating an upstream revision
        ticker=held.ticker,
        as_of=held.as_of,
        horizon_days=held.horizon_days,
        realised_date=held.realised_date,
        realised_close=held.realised_close * 1.01,
    )
    with pytest.raises(RealisedDriftError, match="realised close was"):
        score_item(f, w, band="clean", pin=store.get, record_pin=store.record)


def test_a_shifted_horizon_is_refused_even_at_the_same_price(tmp_path: Path) -> None:
    """A value-only check would miss this, and re-timing the horizon is the more
    dangerous error: the number stays plausible and means a different window."""
    store = _pins(tmp_path)
    f, w = _item()
    score_item(f, w, band="clean", pin=store.get, record_pin=store.record)

    held = store.get(f.ticker, f.as_of.date(), f.horizon_days)
    assert held is not None
    store._pins[held.key] = RealisedPin(  # noqa: SLF001
        ticker=held.ticker,
        as_of=held.as_of,
        horizon_days=held.horizon_days,
        realised_date=date(2020, 1, 2),
        realised_close=held.realised_close,
    )
    with pytest.raises(RealisedDriftError, match="silently re-timed"):
        score_item(f, w, band="clean", pin=store.get, record_pin=store.record)


def test_drift_inside_the_tolerance_is_accepted(tmp_path: Path) -> None:
    """1e-4 relative, matching SPOT_TOLERANCE: float round-tripping through parquet
    must not read as a revision."""
    store = _pins(tmp_path)
    f, w = _item()
    score_item(f, w, band="clean", pin=store.get, record_pin=store.record)
    held = store.get(f.ticker, f.as_of.date(), f.horizon_days)
    assert held is not None
    store._pins[held.key] = RealisedPin(  # noqa: SLF001
        ticker=held.ticker,
        as_of=held.as_of,
        horizon_days=held.horizon_days,
        realised_date=held.realised_date,
        realised_close=held.realised_close * (1 + 5e-5),
    )
    score_item(f, w, band="clean", pin=store.get, record_pin=store.record)


def test_the_store_survives_a_round_trip_to_disk(tmp_path: Path) -> None:
    store = _pins(tmp_path)
    f, w = _item()
    score_item(f, w, band="clean", pin=store.get, record_pin=store.record)

    reopened = RealisedPins(store.path)
    held = reopened.get(f.ticker, f.as_of.date(), f.horizon_days)
    assert held is not None
    assert held.realised_close == pytest.approx(
        realised_bar(w, f.as_of.date(), f.horizon_days).close
    )


def test_a_pin_is_never_overwritten(tmp_path: Path) -> None:
    """A pin that a re-run can replace constrains nothing."""
    store = _pins(tmp_path)
    original = RealisedPin("AAA", date(2026, 1, 5), 5, date(2026, 1, 12), 100.0)
    store.record(original)
    store.record(RealisedPin("AAA", date(2026, 1, 5), 5, date(2026, 1, 12), 999.0))
    held = store.get("AAA", date(2026, 1, 5), 5)
    assert held is not None and held.realised_close == 100.0
    assert store.path.read_text(encoding="utf-8").count("\n") == 1


def test_scoring_without_a_store_is_unchanged(tmp_path: Path) -> None:
    """The callables are optional: nothing about scoring depends on a store existing."""
    f, w = _item()
    assert score_item(f, w, band="clean").realised_return == pytest.approx(
        score_item(f, w, band="clean", pin=None, record_pin=None).realised_return
    )


def test_a_blank_line_in_the_store_is_skipped(tmp_path: Path) -> None:
    """Append-only files acquire blank lines. A pin store that crashed on one would
    lose every pin to a stray newline."""
    path = tmp_path / "realised_pins.jsonl"
    path.write_text(
        '{"ticker":"AAA","as_of":"2026-01-05","horizon_days":5,'
        '"realised_date":"2026-01-12","realised_close":100.0}\n\n',
        encoding="utf-8",
    )
    assert len(RealisedPins(path)) == 1


def test_realised_bar_falls_back_to_the_last_bar_before_the_forecast(tmp_path: Path) -> None:
    """as_of on a non-trading day: the anchor is the previous session, and the pin
    must name the same bar the score used."""
    closes = [100.0 + i for i in range(HORIZON * 3)]
    window = _window(closes)
    saturday = START + timedelta(days=4)  # START is a Monday; +4 is Friday, +5 Saturday
    assert realised_bar(window, saturday + timedelta(days=1), HORIZON).date in {
        bar.date for bar in window.bars
    }


def test_a_horizon_that_has_not_closed_refuses_before_pinning(tmp_path: Path) -> None:
    """WindowNotClosedError must fire from realised_bar too, or a short series would
    be pinned against a bar that does not exist."""
    window = _window([100.0, 101.0, 102.0])
    with pytest.raises(WindowNotClosedError):
        realised_bar(window, START, HORIZON)


def test_realised_bar_refuses_when_no_bar_precedes_the_forecast() -> None:
    """The series starts after the forecast: there is no anchor, and inventing one
    would pin the item to a bar from the wrong side of its own as_of."""
    window = _window([100.0] * (HORIZON * 3), start=START + timedelta(days=30))
    with pytest.raises(ScoringError, match="no bar on or before"):
        realised_bar(window, START, HORIZON)
