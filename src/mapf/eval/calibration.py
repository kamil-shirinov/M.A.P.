"""Whether the fitted correction may be applied to a forecast, and why not.

ADR 0032's map `z -> (z - a) / b` was fitted on 175 development items at a
five-session horizon, drawn from 120 companies the filters in `corpus.selection`
accepted, anchored one trading day after each filing. It generalised to the
holdout — but the holdout is the same panel's other half. Applied to a live
ticker it is an extrapolation, and a corrected fan looks exactly like an
uncorrected one on screen.

So the decision to apply it is made HERE, once, as a value with its reasons
attached, rather than in whatever renders the fan. Two alternatives were
rejected. Deciding in the front end puts credit policy in JavaScript and lets it
drift from the ADR it implements. Writing a boolean onto the run manifest freezes
a policy judgement into a permanent artifact, when the policy may change and the
run may not — and derived values are not persisted anywhere else in this project
either (ADR 0035).

The coefficients are READ FROM THE SPEND RECORD, never hardcoded.
`corpus/holdout_spend.jsonl` is the tracked artifact that carries `a`, `b` and the
form; a second copy in Python would be a number that could disagree with the
record of the single spend that produced it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from mapf.core.errors import MapError

# ADR 0036 §1. Five sessions is the only horizon anything was fitted at, and one
# trading day is the panel's point-in-time alignment — it puts the overnight
# announcement gap outside the window.
FITTED_HORIZON_DAYS = 5
MAX_ANCHOR_LAG_SESSIONS = 1

# The four `RejectionReason` values that are properties of a COMPANY and can
# therefore be evaluated for a live ticker. The other three — `duplicate_cik`,
# `too_few_filings`, `not_reached` — are properties of how the panel was drawn,
# over two fixed calendar windows in a seeded ordering, and have no meaning for a
# single filing today. They are not approximated and not silently passed; ADR 0036
# is where their absence from this test is written down.
COMPANY_SCREENS: tuple[str, ...] = ("no_cik", "no_price_history", "illiquid", "no_exhibit")


class CalibrationError(MapError):
    """The correction was asked for and its terms could not be read."""


@dataclass(frozen=True)
class Correction:
    """The fitted map, as the spend record states it."""

    a: float
    b: float
    form: str
    fitted_on: str
    adr: str

    def apply(self, z: float) -> float:
        return (z - self.a) / self.b


@dataclass(frozen=True)
class Applicability:
    """Whether `Correction` may be applied here, and every reason it may not.

    `reasons` is a tuple rather than a first failure because the screen names the
    failing condition and a forecast can fail several at once. Reporting only the
    first would make a second look like a new problem when the first is fixed.
    """

    applies: bool
    reasons: tuple[str, ...]

    @property
    def marking(self) -> str:
        """`settled` only when every condition held.

        Amber means one thing across this project: a number that is not a settled
        measurement. An uncorrected fan is one, because the uncorrected fan is the
        one measured too narrow — 0.733 on development and 0.592 on the holdout,
        both intervals excluding 1.0.
        """
        return "settled" if self.applies else "uncalibrated"


def load_correction(path: Path) -> Correction:
    """The fitted coefficients, from the record of the single holdout spend.

    Refuses rather than defaulting. There is no sensible fallback: a fan drawn with
    invented coefficients is worse than one drawn raw, because raw is at least a
    thing that was measured.
    """
    if not path.is_file():
        raise CalibrationError(
            f"no spend record at {path}; the fitted coefficients live there and "
            "nowhere else, so the correction cannot be applied"
        )
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise CalibrationError(f"{path} is empty; it should carry the single holdout spend")
    try:
        # The LAST spend, which for a resource spendable once is also the only one.
        # Read positionally rather than asserting a count, so a future amendment
        # appended to the record is picked up instead of refused.
        record = json.loads(lines[-1])
        terms = record["calibration"]
        return Correction(
            a=float(terms["a"]),
            b=float(terms["b"]),
            form=str(terms["form"]),
            fitted_on=str(terms["fitted_on"]),
            adr=str(terms["adr"]),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise CalibrationError(
            f"{path} does not carry readable calibration terms: {error}"
        ) from error


def sessions_between(sessions: Sequence[date], start: date, end: date) -> int | None:
    """Trading days from `start` to `end`, counted on a real session calendar.

    Calendar days would be wrong at every weekend and every holiday: a Friday
    filing anchored the following Monday is one session late and three days late,
    and only one of those two numbers is the panel's alignment. `None` when either
    date is not a session in the series, which is itself a failing condition.
    """
    index = {day: i for i, day in enumerate(sessions)}
    if start not in index or end not in index:
        return None
    return index[end] - index[start]


def applicability(
    *,
    horizon_days: int,
    anchor_lag_sessions: int | None,
    failed_screens: Sequence[str] = (),
    unscreened: Sequence[str] = (),
) -> Applicability:
    """ADR 0036 §1, as a value.

    `anchor_lag_sessions` is `None` when it could not be computed — an anchor or a
    filing date that is not a session in the price series. That is a failure, not a
    pass: a condition nobody could evaluate has not been met.

    `unscreened` names company screens that could not be run at all, which is also
    a failure. The point of the rule is that the correction applies where the panel
    conditions are KNOWN to hold, and an unrun screen is not a held one.
    """
    reasons: list[str] = []
    if horizon_days != FITTED_HORIZON_DAYS:
        reasons.append(
            f"horizon is {horizon_days} sessions; the correction was fitted at "
            f"{FITTED_HORIZON_DAYS} and at no other"
        )
    if anchor_lag_sessions is None:
        reasons.append(
            "the anchor's distance from the filing could not be counted in trading "
            "sessions, so the panel's alignment cannot be confirmed"
        )
    elif not 0 <= anchor_lag_sessions <= MAX_ANCHOR_LAG_SESSIONS:
        reasons.append(
            f"the anchor is {anchor_lag_sessions} sessions from the filing; the panel "
            f"anchors within {MAX_ANCHOR_LAG_SESSIONS}"
        )
    for screen in failed_screens:
        reasons.append(f"the corpus filters would reject this company: {screen}")
    for screen in unscreened:
        reasons.append(f"a corpus filter could not be evaluated here: {screen}")
    return Applicability(applies=not reasons, reasons=tuple(reasons))
