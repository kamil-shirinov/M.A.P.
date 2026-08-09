"""The JSON Schema handed to a constrained decoder.

Docstrings serve developers; the grammar serves the model. `model_json_schema()`
conflates them — it emits every class docstring as a `description` and every field
name as a `title`, so `ScenarioSet`'s schema arrives carrying several hundred
characters of internal prose, including phrases like "the repair loop" and
"ADR 0002". Handing that to Agent 3 would mean a docstring edit silently changes
model behaviour, and a run's output would depend on a comment nobody thought of
as prompt content.

So the decode schema is stripped. If field-level hints are ever wanted, they go in
`json_schema_extra` — curated deliberately, versioned alongside the prompt, and
governed as prompt content under `CLAUDE.md` §4.
"""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel

_PROSE_KEYS = frozenset({"description", "title"})

# Mappings whose *keys* are names chosen by the schema author, not JSON Schema
# keywords. Stripping blindly would delete a field legitimately called `title`.
_NAME_KEYED_MAPPINGS = frozenset(
    {"properties", "$defs", "definitions", "patternProperties", "dependentSchemas"}
)


def _strip(node: Any) -> Any:
    if isinstance(node, dict):
        result: dict[str, Any] = {}
        for key, value in node.items():
            if key in _PROSE_KEYS:
                continue
            if key in _NAME_KEYED_MAPPINGS and isinstance(value, dict):
                # Recurse into the sub-schemas but leave the names themselves alone.
                result[key] = {name: _strip(sub) for name, sub in value.items()}
            else:
                result[key] = _strip(value)
        return result
    if isinstance(node, list):
        return [_strip(item) for item in node]
    return node


def decode_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Emit `model`'s JSON Schema with all human-facing prose removed.

    Constraints are untouched: bounds, string lengths, `required` and
    `additionalProperties` all survive, because those are what make invalid
    tokens unreachable to the sampler (ADR 0002). Only `description` and `title`
    are dropped.
    """
    # `_strip` is recursive over arbitrary JSON, so it is typed Any-in/Any-out.
    # `model_json_schema()` always returns a dict and `_strip` preserves the type
    # of its argument, so the top level is a dict by construction.
    return cast("dict[str, Any]", _strip(model.model_json_schema()))
