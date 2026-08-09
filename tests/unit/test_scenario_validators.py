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


# ---------------------------------------------------------------------------
# bearish < base_case < bullish
# ---------------------------------------------------------------------------
def test_inverted_ordering_is_rejected() -> None:
    with pytest.raises(ValidationError, match="strictly ordered"):
        make_scenario_set(modifiers=(-8.2, 0.8, 4.5))


def test_equal_modifiers_are_rejected() -> None:
    """Ordering is strict. Three identical scenarios are not a forecast."""
    with pytest.raises(ValidationError, match="strictly ordered"):
        make_scenario_set(modifiers=(1.0, 1.0, 1.0))


def test_base_outside_the_bracket_is_rejected() -> None:
    with pytest.raises(ValidationError, match="strictly ordered"):
        make_scenario_set(modifiers=(4.5, 9.9, -8.2))


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
    with pytest.raises(ValidationError):
        make_scenario(justification="x" * 401)


# ---------------------------------------------------------------------------
# price_modifier_pct bounds
# ---------------------------------------------------------------------------
def test_modifier_of_minus_100_is_rejected() -> None:
    """-100% implies a price of zero; anything below implies a negative price."""
    with pytest.raises(ValidationError):
        make_scenario(modifier=-100.0)


def test_modifier_below_minus_100_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_scenario(modifier=-150.0)


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
            price_modifier_pct=1.0,
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
