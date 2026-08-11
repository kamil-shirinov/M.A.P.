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
            "price_modifier_pct": modifier,
            "annualised_vol": 0.3,
        }
        for name, modifier in (("bullish", 4.0), ("base_case", 0.0), ("bearish", -4.0))
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
