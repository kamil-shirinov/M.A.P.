"""Shared builders.

Factories rather than fixtures: nearly every validator test needs a *variant* of a
valid object, and a fixture that must be mutated to be useful is worse than a
function with keyword defaults.
"""

from __future__ import annotations

import os

import pytest

from mapf.core.models import Scenario, ScenarioSet

JUSTIFICATION = "A sufficiently long justification for this scenario branch."


@pytest.fixture(autouse=True)
def _isolate_map_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip `MAP_*` from the environment for every test.

    Settings deliberately let the environment override the file, so a developer
    who has exported `MAP_DATA__SEC__USER_AGENT` in their shell would otherwise
    see different test results from CI — and the placeholder-rejection tests in
    particular would pass for the wrong reason.
    """
    for key in list(os.environ):
        if key.startswith("MAP_"):
            monkeypatch.delenv(key, raising=False)


def make_scenario(
    *,
    weight: float = 0.33,
    modifier: float = 0.0,
    vol: float = 0.25,
    justification: str = JUSTIFICATION,
) -> Scenario:
    return Scenario(
        justification=justification,
        probability_weight=weight,
        price_modifier_pct=modifier,
        annualised_vol=vol,
    )


def make_scenario_set(
    *,
    weights: tuple[float, float, float] = (0.25, 0.60, 0.15),
    modifiers: tuple[float, float, float] = (4.5, 0.8, -8.2),
    vols: tuple[float, float, float] = (0.38, 0.22, 0.55),
    justification: str = JUSTIFICATION,
) -> ScenarioSet:
    """Build a set as (bullish, base_case, bearish) triples."""
    return ScenarioSet(
        bullish=make_scenario(
            weight=weights[0], modifier=modifiers[0], vol=vols[0], justification=justification
        ),
        base_case=make_scenario(
            weight=weights[1], modifier=modifiers[1], vol=vols[1], justification=justification
        ),
        bearish=make_scenario(
            weight=weights[2], modifier=modifiers[2], vol=vols[2], justification=justification
        ),
    )
