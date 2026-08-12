"""The two soft checks. Warnings, never rejections.

Both conditions can be entirely legitimate. What they must not do is pass
silently — the first live run produced a degenerate spread *and* a fabricated
figure, and nothing anywhere said so.
"""

from __future__ import annotations

import pytest

from mapf.core.quality import QualityFlags, check, spread_floor
from tests.conftest import make_scenario, make_scenario_set


def _facts() -> tuple[str, ...]:
    return (
        "Apple's quarterly revenue was $94.9 billion.",
        "Gross margin was 46.3%.",
        "Greater China revenue fell by 6.5% compared to the same period last year.",
    )


# ---------------------------------------------------------------------------
# Degenerate spread
# ---------------------------------------------------------------------------
def test_the_first_live_run_would_now_be_flagged() -> None:
    """0.05 / 0.0 / -0.1 over 21 days: a 0.15 spread reads wide, but those were
    percentage points under the old convention — 0.0015 as a fraction."""
    flags = check(
        make_scenario_set(modifiers=(0.0005, 0.0, -0.001)),
        horizon_days=21,
        facts=_facts(),
    )
    assert flags.degenerate_spread is True
    assert flags.spread < flags.spread_floor


def test_a_realistic_spread_is_not_flagged() -> None:
    flags = check(
        make_scenario_set(modifiers=(0.045, 0.008, -0.082)), horizon_days=21, facts=_facts()
    )
    assert flags.degenerate_spread is False


def test_the_floor_scales_with_the_square_root_of_time() -> None:
    """Price dispersion grows with sqrt(t). A flat threshold would be far too
    tight at one day and far too loose at a year."""
    assert spread_floor(1) == pytest.approx(0.005)
    assert spread_floor(4) == pytest.approx(0.010)
    assert spread_floor(252) == pytest.approx(0.0794, abs=1e-4)


def test_a_spread_acceptable_at_one_day_is_degenerate_at_a_quarter() -> None:
    narrow = make_scenario_set(modifiers=(0.004, 0.0, -0.004))
    assert check(narrow, horizon_days=1, facts=_facts()).degenerate_spread is False
    assert check(narrow, horizon_days=63, facts=_facts()).degenerate_spread is True


def test_a_genuinely_flat_outlook_is_still_a_valid_forecast() -> None:
    """A warning, not a validator. Rejecting this would suppress real forecasts to
    catch occasional bad ones."""
    flags = check(
        make_scenario_set(modifiers=(0.001, 0.0, -0.001)), horizon_days=21, facts=_facts()
    )
    assert flags.degenerate_spread is True
    assert flags.any_flag is True  # recorded, not raised


# ---------------------------------------------------------------------------
# Ungrounded numerals
# ---------------------------------------------------------------------------
def test_the_fabricated_gross_margin_is_caught_in_the_real_output() -> None:
    """Not a synthetic string written to be caught — the actual raw response from
    the first live run, pinned as a fixture because it reproduces on demand.

    A test written against invented input proves the regex works. This proves the
    check catches the failure that actually happened.
    """
    import json
    from pathlib import Path

    from mapf.core.quality import _numerals

    fixture = json.loads(
        (
            Path(__file__).parents[1] / "fixtures" / "hallucination" / "structuralist-66pt3.json"
        ).read_text(encoding="utf-8")
    )
    emitted = json.loads(fixture["raw_response"])
    justification = emitted["base_case"]["justification"]
    assert "66.3" in justification

    grounded = _numerals(fixture["source_fact"])
    found = _numerals(justification)
    ungrounded = [v for v in found if not any(abs(v - k) <= max(0.05, 0.01 * k) for k in grounded)]
    assert 66.3 in ungrounded
    assert 46.3 not in found  # the model replaced it rather than adding to it


def test_the_fabricated_gross_margin_is_caught() -> None:
    """The exact incident: the source said 46.3%, the analyst said 46.3%, and the
    structuralist wrote 66.3%. Every validator passed."""
    scenarios = make_scenario_set()
    scenarios = scenarios.model_copy(
        update={
            "base_case": make_scenario(
                modifier=0.008,
                justification="The high gross margin of 66.3% suggests a stable profit floor.",
            )
        }
    )
    flags = check(scenarios, horizon_days=21, facts=_facts())
    assert any("66.3" in v for v in flags.ungrounded_numerals)


def test_figures_that_trace_to_a_fact_are_not_flagged() -> None:
    scenarios = make_scenario_set()
    scenarios = scenarios.model_copy(
        update={
            "base_case": make_scenario(
                modifier=0.008,
                justification="A 6.5% fall in Greater China against a 46.3% gross margin.",
            )
        }
    )
    assert check(scenarios, horizon_days=21, facts=_facts()).ungrounded_numerals == ()


def test_rounding_is_tolerated() -> None:
    """Models paraphrase and round. Flagging 46.3 written as 46 would bury the
    signal under noise."""
    scenarios = make_scenario_set()
    scenarios = scenarios.model_copy(
        update={
            "base_case": make_scenario(
                modifier=0.008, justification="Gross margin of about 46% is comfortable."
            )
        }
    )
    assert check(scenarios, horizon_days=21, facts=_facts()).ungrounded_numerals == ()


def test_the_check_is_crude_and_that_is_stated() -> None:
    """Recall is not high — "just over 46 percent" for 46.3 slips through, and
    prose without digits cannot be checked at all. It converts an invisible
    failure into a visible one *sometimes*, which is still worth having."""
    scenarios = make_scenario_set()
    scenarios = scenarios.model_copy(
        update={
            "base_case": make_scenario(
                modifier=0.008,
                justification="Margins are comfortably above the mid-forties on any reading.",
            )
        }
    )
    assert check(scenarios, horizon_days=21, facts=_facts()).ungrounded_numerals == ()


def test_flags_default_to_clean() -> None:
    assert QualityFlags().any_flag is False


def test_a_clean_forecast_carries_no_flags() -> None:
    flags = check(
        make_scenario_set(modifiers=(0.045, 0.008, -0.082)), horizon_days=21, facts=_facts()
    )
    assert flags.any_flag is False


def test_the_horizon_is_not_a_fabrication() -> None:
    """The first v2 live run flagged "21" from "a 21-day horizon". The model is
    told the horizon; treating it as invented buries the signal under noise."""
    scenarios = make_scenario_set()
    scenarios = scenarios.model_copy(
        update={
            "base_case": make_scenario(
                modifier=0.008,
                justification="Over a 21-day horizon a large-cap rarely moves dramatically.",
            )
        }
    )
    assert check(scenarios, horizon_days=21, facts=_facts()).ungrounded_numerals == ()


def test_the_spot_price_is_not_a_fabrication() -> None:
    scenarios = make_scenario_set()
    scenarios = scenarios.model_copy(
        update={
            "base_case": make_scenario(
                modifier=0.008, justification="From 304.91 the downside looks contained."
            )
        }
    )
    flags = check(scenarios, horizon_days=21, facts=_facts(), spot_price=304.91)
    assert flags.ungrounded_numerals == ()
