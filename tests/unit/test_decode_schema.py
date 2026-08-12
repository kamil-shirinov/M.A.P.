"""The decode schema must carry no prose.

This test *is* the enforcement. Without it the leak returns the first time someone
writes a helpful docstring on a domain model, and the symptom would be a silent
change in Agent 3's behaviour with no diff that looks like a prompt edit.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mapf.core.models import Forecast, ScenarioSet
from mapf.core.schema import decode_schema


def _walk(node: Any) -> list[str]:
    """Every dict key in the tree, at any depth."""
    keys: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            keys.append(key)
            keys.extend(_walk(value))
    elif isinstance(node, list):
        for item in node:
            keys.extend(_walk(item))
    return keys


def test_scenario_set_decode_schema_has_no_prose_at_any_depth() -> None:
    keys = _walk(decode_schema(ScenarioSet))
    assert "description" not in keys
    assert "title" not in keys


def test_forecast_decode_schema_has_no_prose_at_any_depth() -> None:
    """Not decoded today (ADR 0002), but it must not become a leak if that changes."""
    keys = _walk(decode_schema(Forecast))
    assert "description" not in keys
    assert "title" not in keys


def test_pydantic_really_does_emit_the_prose_we_are_stripping() -> None:
    """Guards the premise. If pydantic ever stops emitting descriptions, this test
    fails and `decode_schema` becomes dead code that should be reconsidered rather
    than silently kept."""
    raw = _walk(ScenarioSet.model_json_schema())
    assert "description" in raw
    assert "title" in raw


def test_constraints_survive_stripping() -> None:
    """Only prose is removed. The bounds are what make invalid tokens unreachable."""
    scenario = decode_schema(ScenarioSet)["$defs"]["Scenario"]
    assert scenario["additionalProperties"] is False
    assert scenario["required"] == [
        "justification",
        "probability_weight",
        "price_return",
        "annualised_vol",
    ]
    assert scenario["properties"]["justification"]["minLength"] == 20
    assert scenario["properties"]["justification"]["maxLength"] == 400
    assert scenario["properties"]["annualised_vol"]["exclusiveMinimum"] == 0.0
    assert scenario["properties"]["annualised_vol"]["maximum"] == 3.0
    assert scenario["properties"]["price_return"]["exclusiveMinimum"] == -1.0
    assert scenario["properties"]["probability_weight"]["minimum"] == 0.0
    assert scenario["properties"]["probability_weight"]["maximum"] == 1.0


def test_field_order_is_preserved() -> None:
    """A constrained decoder emits in schema order, so this is load-bearing:
    `justification` must come first (ADR 0006)."""
    properties = decode_schema(ScenarioSet)["$defs"]["Scenario"]["properties"]
    assert next(iter(properties)) == "justification"


def test_a_field_named_title_is_not_deleted() -> None:
    """`properties` keys are author-chosen names, not JSON Schema keywords.

    Stripping blindly would silently drop a field called `title` from the grammar,
    and the model would then be unable to emit it at all.
    """

    class HasAwkwardFieldNames(BaseModel):
        model_config = ConfigDict(extra="forbid")

        title: str = Field(min_length=1)
        description: str = Field(min_length=1)

    schema = decode_schema(HasAwkwardFieldNames)
    assert set(schema["properties"]) == {"title", "description"}
    assert schema["properties"]["title"]["minLength"] == 1
    # ...but the auto-generated prose *about* those fields is still gone.
    assert "title" not in schema["properties"]["title"]
