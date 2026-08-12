"""Validators must *reject*, not warn.

These are the invariants a constrained-decoding grammar cannot express — they
span fields, and JSON Schema has no vocabulary for "these three numbers sum to
one" (ADR 0002). If any test here passes an invalid object, the repair loop has
nothing to react to and a malformed forecast reaches disk looking authoritative.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mapf.core.models import Scenario, ScenarioSet
from tests.conftest import JUSTIFICATION, make_scenario, make_scenario_set


def test_valid_set_is_accepted() -> None:
    scenarios = make_scenario_set()
    assert scenarios.base_case.probability_weight == pytest.approx(0.60)


# ---------------------------------------------------------------------------
# probability_weight must sum to 1.0 +/- 1e-6
# ---------------------------------------------------------------------------
def test_weights_summing_to_099_are_rejected() -> None:
    with pytest.raises(ValidationError, match="sum to 1.0"):
        make_scenario_set(weights=(0.25, 0.60, 0.14))


def test_weights_summing_above_one_are_rejected() -> None:
    with pytest.raises(ValidationError, match="sum to 1.0"):
        make_scenario_set(weights=(0.30, 0.60, 0.15))


def test_weights_within_tolerance_are_accepted() -> None:
    """1e-7 off. Float arithmetic on three decimals cannot be exact, so a
    tolerance is required; 1e-6 is tight enough to catch a model that guessed."""
    scenarios = make_scenario_set(weights=(0.25, 0.60, 0.1500001))
    total = (
        scenarios.bullish.probability_weight
        + scenarios.base_case.probability_weight
        + scenarios.bearish.probability_weight
    )
    assert total == pytest.approx(1.0, abs=1e-6)


def test_weights_outside_tolerance_are_rejected() -> None:
    with pytest.raises(ValidationError, match="sum to 1.0"):
        make_scenario_set(weights=(0.25, 0.60, 0.15001))


def test_negative_weight_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_scenario(weight=-0.1)


# --- adversarial float triples ------------------------------------------------
# Hand-picked cases cluster where intuition is good and float arithmetic is not.
# These are the cases that decide whether the tolerance is the right shape.


@pytest.mark.parametrize(
    "weights",
    [
        (0.333, 0.333, 0.334),  # three decimals that happen to sum exactly
        (0.1, 0.2, 0.7),  # the canonical 0.1+0.2 case
        (1 / 3, 1 / 3, 1 / 3),  # non-terminating in binary
        (0.05, 0.15, 0.80),
        (0.07, 0.13, 0.80),
        (0.01, 0.29, 0.70),
    ],
)
def test_exact_decimal_triples_are_accepted(weights: tuple[float, float, float]) -> None:
    """None of these is exactly representable, and every one must still pass.

    A validator demanding `total == 1.0` would reject several of them outright,
    which is the failure this tolerance exists to prevent.
    """
    assert make_scenario_set(weights=weights) is not None


def test_summation_order_can_change_the_total() -> None:
    """(0.1, 0.2, 0.7) sums to exactly 1.0 in one association order and to
    0.9999999999999999 in another.

    The error is ~1.1e-16, far inside tolerance, so behaviour does not change —
    but it is direct evidence that the tolerance is load-bearing rather than
    decorative, and that an equality check would make acceptance depend on which
    branch happened to be added first.
    """
    assert 0.1 + 0.2 + 0.7 != 0.2 + 0.7 + 0.1
    assert make_scenario_set(weights=(0.1, 0.2, 0.7)) is not None
    assert make_scenario_set(weights=(0.2, 0.7, 0.1)) is not None


@pytest.mark.parametrize("third", [0.1500001, 0.1499999])
def test_one_tenth_of_tolerance_off_is_accepted(third: float) -> None:
    """+/-1e-7 on either side. Both give |total - 1| ~= 1.0000000006e-07."""
    assert make_scenario_set(weights=(0.25, 0.60, third)) is not None


@pytest.mark.parametrize("third", [0.1500011, 0.1499989, 0.15001, 0.14999])
def test_just_over_tolerance_is_rejected_on_both_sides(third: float) -> None:
    """+/-1.1e-6 and +/-1e-5. The first pair is the one that matters: it is only
    10% outside the limit, and it must still fail."""
    with pytest.raises(ValidationError, match="sum to 1.0"):
        make_scenario_set(weights=(0.25, 0.60, third))


def test_the_tolerance_boundary_itself_is_asymmetric() -> None:
    """A nominal deviation of exactly 1e-6 is accepted above 1.0 and rejected below.

    `0.25 + 0.60 + 0.150001` -> |diff| = 9.99999999917733e-07  (inside, accepted)
    `0.25 + 0.60 + 0.149999` -> |diff| = 1.00000000002876e-06  (outside, rejected)

    Neither number is 1e-6; both are the nearest representable double to it, and
    they land on opposite sides. This is a property of binary floating point, not
    of the validator, and it cannot be tuned away — any threshold has an edge with
    this behaviour.

    It is pinned here so that changing the comparison (`>` to `>=`, or moving to
    `math.isclose`) shows up as a failing test rather than as a silent shift in
    which forecasts are accepted. No other test may depend on the exact boundary.
    """
    assert make_scenario_set(weights=(0.25, 0.60, 0.150001)) is not None
    with pytest.raises(ValidationError, match="sum to 1.0"):
        make_scenario_set(weights=(0.25, 0.60, 0.149999))


def test_weights_that_are_individually_valid_but_jointly_wrong_are_rejected() -> None:
    """Each weight is inside [0, 1], so a per-field grammar constraint passes.

    This is precisely the gap JSON Schema cannot express and the repair loop must
    answer (ADR 0002).
    """
    with pytest.raises(ValidationError, match="sum to 1.0"):
        make_scenario_set(weights=(0.5, 0.5, 0.5))


# ---------------------------------------------------------------------------
# bearish < base_case < bullish
# ---------------------------------------------------------------------------
def test_inverted_ordering_is_rejected() -> None:
    with pytest.raises(ValidationError, match="strictly ordered"):
        make_scenario_set(modifiers=(-0.082, 0.008, 0.045))


def test_equal_modifiers_are_rejected() -> None:
    """Ordering is strict. Three identical scenarios are not a forecast."""
    with pytest.raises(ValidationError, match="strictly ordered"):
        make_scenario_set(modifiers=(0.01, 0.01, 0.01))


def test_base_outside_the_bracket_is_rejected() -> None:
    with pytest.raises(ValidationError, match="strictly ordered"):
        make_scenario_set(modifiers=(0.045, 0.099, -0.082))


# ---------------------------------------------------------------------------
# annualised_vol in (0, 3.0]
# ---------------------------------------------------------------------------
def test_vol_of_zero_is_rejected() -> None:
    """A zero-vol scenario is a point claim with certainty attached."""
    with pytest.raises(ValidationError):
        make_scenario(vol=0.0)


def test_vol_above_maximum_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_scenario(vol=3.1)


def test_vol_at_maximum_is_accepted() -> None:
    assert make_scenario(vol=3.0).annualised_vol == pytest.approx(3.0)


def test_negative_vol_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_scenario(vol=-0.2)


# ---------------------------------------------------------------------------
# justification length
# ---------------------------------------------------------------------------
def test_justification_of_19_chars_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_scenario(justification="x" * 19)


def test_justification_of_20_chars_is_accepted() -> None:
    assert len(make_scenario(justification="x" * 20).justification) == 20


def test_justification_of_400_chars_is_accepted() -> None:
    assert len(make_scenario(justification="x" * 400).justification) == 400


def test_justification_of_401_chars_is_rejected() -> None:
    """400, restored. It was cut to 240 on the theory that a budget too small to
    paste into forces compression; ADR 0014 records that theory as wrong — at 240
    the model still pasted and still truncated. What stopped the copying was the v2
    instruction "the justification is yours". `justifications_at_ceiling` in the
    manifest is the regression signal that makes the larger ceiling safe."""
    with pytest.raises(ValidationError):
        make_scenario(justification="x" * 401)


# ---------------------------------------------------------------------------
# price_return bounds
# ---------------------------------------------------------------------------
def test_a_total_loss_return_is_rejected() -> None:
    """-1.0 is a price of zero; anything below is a negative price."""
    with pytest.raises(ValidationError):
        make_scenario(modifier=-1.0)


def test_a_return_below_total_loss_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_scenario(modifier=-1.5)


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------
def test_extra_fields_are_forbidden() -> None:
    """`extra="forbid"` is what renders `additionalProperties: false` into the
    grammar, so a model cannot invent a field the pipeline will not read."""
    with pytest.raises(ValidationError):
        Scenario(
            justification=JUSTIFICATION,
            probability_weight=0.5,
            price_return=0.01,
            annualised_vol=0.2,
            confidence=0.9,  # type: ignore[call-arg]
        )


def test_scenario_set_is_frozen() -> None:
    scenarios = make_scenario_set()
    with pytest.raises(ValidationError):
        scenarios.bullish = make_scenario()  # type: ignore[misc]


def test_missing_branch_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ScenarioSet(bullish=make_scenario(), base_case=make_scenario())  # type: ignore[call-arg]
