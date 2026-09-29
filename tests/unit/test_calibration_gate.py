"""ADR 0036 §1 — when the fitted correction may be applied, and why not.

The rule is conservative on purpose, so most of these tests are about the ways it
refuses. A gate that almost never fires would not be doing anything.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from mapf.eval.calibration import (
    COMPANY_SCREENS,
    Applicability,
    CalibrationError,
    Correction,
    applicability,
    load_correction,
    sessions_between,
)

SPEND = Path(__file__).parents[2] / "corpus" / "holdout_spend.jsonl"


def _ok(**over: object) -> Applicability:
    base: dict[str, object] = {"horizon_days": 5, "anchor_lag_sessions": 1}
    return applicability(**{**base, **over})  # type: ignore[arg-type]


# --- the coefficients come from the record, never from Python -----------------


def test_the_coefficients_are_read_from_the_committed_spend_record() -> None:
    """A second copy in code is a number that can disagree with the record of the
    single spend that produced it."""
    correction = load_correction(SPEND)
    assert correction.a == pytest.approx(-0.0757)
    assert correction.b == pytest.approx(1.3305)
    assert correction.form == "z -> (z - a) / b"
    assert correction.adr == "0032"


def test_the_map_is_the_one_the_record_states() -> None:
    correction = Correction(a=-0.0757, b=1.3305, form="z -> (z - a) / b", fitted_on="", adr="")
    assert correction.apply(0.0) == pytest.approx(0.0757 / 1.3305)
    assert correction.apply(-0.0757) == pytest.approx(0.0)
    # b > 1, so the corrected z is pulled toward zero: the intervals widen, which
    # is what a fan measured too narrow needs.
    assert abs(correction.apply(2.0)) < 2.0


def test_a_missing_spend_record_refuses_rather_than_defaulting(tmp_path: Path) -> None:
    """There is no sensible fallback. A fan drawn with invented coefficients is
    worse than a raw one, because raw is at least something that was measured."""
    with pytest.raises(CalibrationError, match="nowhere else"):
        load_correction(tmp_path / "absent.jsonl")


def test_an_empty_or_unreadable_record_refuses(tmp_path: Path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n\n")
    with pytest.raises(CalibrationError, match="empty"):
        load_correction(empty)

    junk = tmp_path / "junk.jsonl"
    junk.write_text('{"band": "clean"}\n')
    with pytest.raises(CalibrationError, match="readable calibration terms"):
        load_correction(junk)


def test_a_later_amendment_is_read_rather_than_refused(tmp_path: Path) -> None:
    """Positional, not a count assertion: an amendment appended to the record should
    be picked up, not rejected for making the file two lines long."""
    path = tmp_path / "spend.jsonl"
    first = {"calibration": {"a": -0.07, "b": 1.33, "form": "f", "fitted_on": "x", "adr": "0032"}}
    later = {"calibration": {"a": -0.08, "b": 1.40, "form": "f", "fitted_on": "y", "adr": "0032"}}
    path.write_text(json.dumps(first) + "\n" + json.dumps(later) + "\n")
    assert load_correction(path).b == pytest.approx(1.40)


# --- the three conditions ------------------------------------------------------


def test_all_three_conditions_met_applies_the_correction() -> None:
    decision = _ok()
    assert decision.applies is True
    assert decision.reasons == ()
    assert decision.marking == "settled"


def test_the_panel_alignment_allows_the_filing_day_itself() -> None:
    # Within one session, not exactly one: an anchor on the filing day is inside
    # the panel's alignment, not outside it.
    assert _ok(anchor_lag_sessions=0).applies is True


def test_a_horizon_other_than_five_refuses_and_says_so() -> None:
    """Ten and twenty-one sessions are offered by the period selector and nothing
    was fitted at either."""
    for horizon in (10, 21):
        decision = _ok(horizon_days=horizon)
        assert decision.applies is False
        assert decision.marking == "uncalibrated"
        assert any(f"and this is {horizon}" in r for r in decision.reasons)
        assert any("only tested over 5 sessions" in r for r in decision.reasons)


def test_an_anchor_too_far_from_the_filing_refuses() -> None:
    decision = _ok(anchor_lag_sessions=3)
    assert decision.applies is False
    assert any("this forecast is 3 trading days after one" in r for r in decision.reasons)


def test_an_uncountable_anchor_lag_is_a_failure_not_a_pass() -> None:
    """A condition nobody could evaluate has not been met. The alternative —
    treating `None` as fine — is how an unchecked case becomes a silent pass."""
    decision = _ok(anchor_lag_sessions=None)
    assert decision.applies is False
    assert any("could not be counted in" in r for r in decision.reasons)


def test_a_failed_company_screen_refuses_and_names_it() -> None:
    decision = _ok(failed_screens=["illiquid"])
    assert decision.applies is False
    assert any("illiquid" in r for r in decision.reasons)


def test_every_reason_is_a_sentence_a_reader_can_act_on() -> None:
    """These strings are printed verbatim in the amber box, so they are screen
    copy rather than internal labels. "the panel anchors within 1" told a reader
    nothing they could use; "the correction was only tested within 1 trading day
    of a filing" tells them what the limit is and why it bites."""
    decision = _ok(horizon_days=21, anchor_lag_sessions=9, failed_screens=["illiquid"])
    for reason in decision.reasons:
        assert "panel" not in reason, reason
        assert "anchor is" not in reason, reason
        assert reason[0].islower() and len(reason.split()) >= 8, reason


def test_an_unrun_company_screen_is_also_a_failure() -> None:
    """The rule is that the panel conditions are KNOWN to hold. An unrun screen is
    not a held one."""
    decision = _ok(unscreened=["no_exhibit"])
    assert decision.applies is False
    assert any("could not be run here" in r for r in decision.reasons)


def test_every_failing_condition_is_reported_not_just_the_first() -> None:
    """Reporting only the first makes the second look like a new problem once the
    first is fixed."""
    decision = _ok(horizon_days=21, anchor_lag_sessions=9, failed_screens=["illiquid", "no_cik"])
    assert len(decision.reasons) == 4


def test_only_the_company_level_screens_are_in_the_test() -> None:
    """The other three RejectionReason values are properties of how the panel was
    drawn — a seeded ordering over two fixed calendar windows — and have no meaning
    for one filing today. Pinned so adding one later is a deliberate act."""
    assert COMPANY_SCREENS == ("no_cik", "no_price_history", "illiquid", "no_exhibit")
    for drawn in ("duplicate_cik", "too_few_filings", "not_reached"):
        assert drawn not in COMPANY_SCREENS


# --- the session count ---------------------------------------------------------


def test_sessions_are_counted_on_the_calendar_not_in_days() -> None:
    """A Friday filing anchored the following Monday is one session late and three
    days late. Only one of those is the panel's alignment."""
    sessions = [date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 28), date(2026, 9, 29)]
    assert sessions_between(sessions, date(2026, 9, 25), date(2026, 9, 28)) == 1
    assert (date(2026, 9, 28) - date(2026, 9, 25)).days == 3


def test_a_filing_that_is_not_a_session_gives_no_count() -> None:
    """The START has to be a real session. Nothing can be counted from a day the
    market was shut."""
    sessions = [date(2026, 9, 24), date(2026, 9, 25)]
    assert sessions_between(sessions, date(2026, 9, 26), date(2026, 9, 25)) is None


def test_an_anchor_past_the_last_session_counts_as_a_lower_bound() -> None:
    """A live run anchored today, before today's close, has no bar for its own
    anchor. Refusing to count there was correct and useless: the filing was two
    months back, and a lower bound settles "is this within one session" outright.

    It reached the screen as "could not be counted in trading days", which told a
    reader nothing about a question that was never in doubt."""
    sessions = [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)]
    assert sessions_between(sessions, date(2026, 9, 21), date(2026, 9, 30)) == 2
    assert sessions_between(sessions, date(2026, 9, 23), date(2026, 9, 30)) == 0


def test_a_gap_inside_the_series_is_still_refused() -> None:
    """A date the series simply lacks — a holiday in the middle — is not a lower
    bound, it is a hole. Only an end past the LAST session is countable."""
    sessions = [date(2026, 9, 21), date(2026, 9, 25)]
    assert sessions_between(sessions, date(2026, 9, 21), date(2026, 9, 23)) is None


def test_an_empty_calendar_counts_nothing() -> None:
    assert sessions_between([], date(2026, 9, 21), date(2026, 9, 30)) is None


def test_an_anchor_before_the_filing_is_negative_and_refused() -> None:
    """A forecast anchored before the document it reads is a look-ahead the wrong
    way round, and the gate refuses it rather than taking an absolute value."""
    decision = _ok(anchor_lag_sessions=-1)
    assert decision.applies is False
