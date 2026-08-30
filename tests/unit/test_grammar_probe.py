"""The grammar probe: does the backend accept `$defs`/`$ref`?

Open question 8, the most likely first-run failure. Without the probe it would
surface at the end of a three-minute pipeline after two model swaps.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from mapf.core.errors import (
    InferenceProtocolError,
    InferenceStatusError,
    InferenceTimeoutError,
    InferenceUnreachableError,
)
from mapf.core.models import ScenarioSet
from mapf.core.ports import LLMResponse, ModelInfo, SamplingParams
from mapf.core.schema import decode_schema
from mapf.pipeline.probe import probe_grammar
from mapf.prompts.loader import FilePromptStore

MODEL = ModelInfo(id="qwen3-4b", fingerprint="fp", fingerprint_source="tag")
SAMPLING = SamplingParams(temperature=0.0)

VALID = json.dumps(
    {
        name: {
            "justification": "A sufficiently long placeholder justification here.",
            "probability_weight": 0.33,
            "price_return": modifier,
            "annualised_vol": 0.3,
        }
        for name, modifier in (("bullish", 0.04), ("base_case", 0.0), ("bearish", -0.04))
    }
)


class _Provider:
    def __init__(self, *, text: str | None = None, error: Exception | None = None) -> None:
        self._text = text
        self._error = error
        self.schemas: list[Any] = []
        self.calls = 0

    def list_models(self) -> tuple[ModelInfo, ...]:
        return (MODEL,)

    def complete(self, *, model: ModelInfo, prompt: Any, sampling: Any, **kwargs: Any) -> Any:
        self.calls += 1
        self.schemas.append(kwargs.get("json_schema"))
        if self._error is not None:
            raise self._error
        return LLMResponse(text=self._text or "", model_id=model.id)


def _probe(provider: _Provider) -> Any:
    return probe_grammar(
        provider=provider, prompts=FilePromptStore(), model=MODEL, sampling=SAMPLING
    )


def test_a_backend_that_honours_the_schema_reports_enforced() -> None:
    assert _probe(_Provider(text=VALID)).outcome == "enforced"


def test_the_probe_sends_the_real_decode_schema() -> None:
    """A probe against a simplified schema would test the wrong thing — the whole
    question is whether `$defs`/`$ref` resolve, and those only appear in the real one."""
    provider = _Provider(text=VALID)
    _probe(provider)
    schema = provider.schemas[0]
    assert schema == decode_schema(ScenarioSet)
    assert "$defs" in schema
    assert schema["properties"]["bullish"] == {"$ref": "#/$defs/Scenario"}


def test_a_rejected_schema_names_the_flattening_fix() -> None:
    result = _probe(_Provider(error=InferenceStatusError(400, "grammar compile failed")))
    assert result.outcome == "rejected"
    assert result.remedy is not None
    assert "Flatten the schema" in result.remedy
    assert "decode_schema" in result.remedy


def test_prose_back_from_a_constrained_request_is_not_enforcement() -> None:
    """The dangerous middle case: 200 OK and no grammar. It would look identical to
    a working backend until Agent 3 failed validation on every single attempt."""
    result = _probe(_Provider(text="Sure! Here are three scenarios..."))
    assert result.outcome == "accepted_not_enforced"
    assert "ignored it" in result.detail


def test_json_of_the_wrong_shape_is_not_enforcement() -> None:
    result = _probe(_Provider(text='{"scenarios": []}'))
    assert result.outcome == "accepted_not_enforced"


def test_a_timeout_is_inconclusive_not_a_failure() -> None:
    """On this hardware a cold 12B load routinely exceeds a short read timeout.
    Calling that a rejected schema would send someone rewriting the wrong thing."""
    result = _probe(_Provider(error=InferenceTimeoutError("qwen3-4b", 600.0)))
    assert result.outcome == "inconclusive"
    assert result.remedy is not None
    assert "again" in result.remedy


@pytest.mark.parametrize(
    "error",
    [InferenceUnreachableError("http://x/v1", "refused"), InferenceProtocolError("garbled")],
)
def test_other_inference_failures_are_inconclusive(error: Exception) -> None:
    assert _probe(_Provider(error=error)).outcome == "inconclusive"


def test_the_probe_does_not_validate_the_placeholder_forecast() -> None:
    """It asks whether the grammar held, not whether a throwaway answer is a good
    forecast. Weights summing to 0.99 here are the repair loop's business."""
    weak = json.loads(VALID)
    weak["bullish"]["probability_weight"] = 0.99
    assert _probe(_Provider(text=json.dumps(weak))).outcome == "enforced"


def test_the_probe_costs_exactly_one_call() -> None:
    provider = _Provider(text=VALID)
    _probe(provider)
    assert provider.calls == 1


def test_the_result_exposes_a_plain_ok_flag() -> None:
    """`ok` is what a caller branches on; only "enforced" is a pass. An
    inconclusive probe must not read as a green light."""
    assert _probe(_Provider(text=VALID)).ok is True
    assert _probe(_Provider(text="prose")).ok is False
    assert _probe(_Provider(error=InferenceProtocolError("x"))).ok is False


# ---------------------------------------------------------------------------
# Exact shape, not a superset (ADR 0022)
# ---------------------------------------------------------------------------
def test_an_extra_top_level_key_is_evidence_against_enforcement() -> None:
    """This was scored as `enforced` until the guard audit — an inverted test.

    `additionalProperties: false` makes an extra key unreachable under a grammar
    the sampler is actually constrained by, so its presence proves the opposite of
    what the old `>=` check concluded from it.
    """
    loose = json.loads(VALID)
    loose["commentary"] = "here is my reasoning"
    probe = _probe(_Provider(text=json.dumps(loose)))
    assert probe.outcome == "accepted_not_enforced"
    assert "commentary" in probe.detail


def test_a_missing_branch_is_still_caught() -> None:
    partial = json.loads(VALID)
    del partial["bearish"]
    assert _probe(_Provider(text=json.dumps(partial))).outcome == "accepted_not_enforced"


def test_an_extra_field_inside_a_branch_is_caught() -> None:
    """The same reasoning one level down: the grammar constrains the whole tree,
    so a shape check that stops at the top level tests only half of it."""
    loose = json.loads(VALID)
    loose["bullish"]["confidence"] = "high"
    probe = _probe(_Provider(text=json.dumps(loose)))
    assert probe.outcome == "accepted_not_enforced"
    assert "bullish" in probe.detail


def test_a_missing_field_inside_a_branch_is_caught() -> None:
    partial = json.loads(VALID)
    del partial["base_case"]["annualised_vol"]
    assert _probe(_Provider(text=json.dumps(partial))).outcome == "accepted_not_enforced"


def test_a_branch_that_is_not_an_object_is_caught() -> None:
    wrong = json.loads(VALID)
    wrong["bearish"] = "sharply down"
    assert _probe(_Provider(text=json.dumps(wrong))).outcome == "accepted_not_enforced"


def test_a_json_array_is_not_an_object() -> None:
    assert _probe(_Provider(text="[1, 2, 3]")).outcome == "accepted_not_enforced"


def test_the_expected_fields_are_read_from_the_model() -> None:
    """Restating them here would let a field added to `Scenario` leave the probe
    checking a shape the pipeline no longer uses."""
    from mapf.core.models import Scenario
    from mapf.pipeline.probe import FIELDS

    assert set(Scenario.model_fields) == FIELDS
