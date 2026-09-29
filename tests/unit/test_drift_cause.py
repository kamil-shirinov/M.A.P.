"""A drift says WHY the recorded price and the snapshot disagree.

Two causes, not interchangeable. SCCO's seven runs read settled closes that a
later corporate action re-based. AAPL's two read a bar still trading and were
never closes. Every screen called all nine "re-based by a corporate action",
guessing the cause from the fact of a ratio. The cause now comes from
`price_kind`, which comes from what each run recorded.
"""

from __future__ import annotations

from datetime import date

from mapf.core.models import Bar, PriceWindow
from mapf.eval.journal import _drift

ANCHOR = date(2026, 8, 13)


def _window(close: float) -> PriceWindow:
    return PriceWindow(
        ticker="AAPL",
        provider="yfinance",
        adjustment="split_adjusted",
        bars=(Bar(date=ANCHOR, open=close, high=close, low=close, close=close, volume=1),),
    )


def test_a_mid_session_anchor_is_named_as_such() -> None:
    drift = _drift(_window(305.26), ANCHOR, 302.985, "intraday")
    assert drift is not None
    assert drift.cause == "intraday_anchor"


def test_a_settled_anchor_that_moved_is_a_corporate_action() -> None:
    drift = _drift(_window(89.08), ANCHOR, 90.1498, "close")
    assert drift is not None
    assert drift.cause == "corporate_action"


def test_an_unclassified_anchor_says_so_rather_than_guessing() -> None:
    drift = _drift(_window(305.26), ANCHOR, 302.985, "unknown")
    assert drift is not None
    assert drift.cause == "unknown"


def test_the_cause_is_not_read_from_the_size_of_the_ratio() -> None:
    """A 0.75% factor gave AAPL away because it is neither a split nor a plausible
    dividend — but a rule built on that would be wrong the first time a small
    dividend and a quiet afternoon produced the same number. Same ratio, two
    causes, decided only by what the run recorded."""
    same_ratio_close = _drift(_window(305.26), ANCHOR, 302.985, "close")
    same_ratio_intraday = _drift(_window(305.26), ANCHOR, 302.985, "intraday")
    assert same_ratio_close is not None and same_ratio_intraday is not None
    assert same_ratio_close.ratio == same_ratio_intraday.ratio
    assert same_ratio_close.cause != same_ratio_intraday.cause


def test_agreement_within_tolerance_is_no_drift_whatever_the_kind() -> None:
    assert _drift(_window(302.985), ANCHOR, 302.985, "intraday") is None
