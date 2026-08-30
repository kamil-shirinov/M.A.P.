"""The runaway that left no evidence (ADR 0027).

Two items burned the analyst's entire 12,000-token budget and produced no answer.
Asked afterwards whether that was a decoding loop or genuinely long reasoning, the
recorded data could not say — because `ModelBudgetExhaustedError` is raised while
parsing the response and the trace write sat *after* it, so the call left no event at
all; and because the reasoning text was never captured on any call, successful or not.

**The failure that most needed diagnosing was the only one with no evidence.**
"""

from __future__ import annotations

from typing import Any

import pytest

from mapf.agents.base import LLMAgent
from mapf.core.errors import ModelBudgetExhaustedError
from mapf.core.ports import (
    LLMResponse,
    Message,
    ModelInfo,
    RenderedPrompt,
    SamplingParams,
)
from mapf.pipeline.trace import CountingTrace

MODEL = ModelInfo(id="m", fingerprint="tag:m", fingerprint_source="tag")
PROMPT = RenderedPrompt(
    template_name="analyst",
    template_version="v3",
    template_sha256="0" * 64,
    messages=(Message(role="user", content="facts"),),
)
LOOP = "The quarter was strong.\n" * 400


class _Sink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


class _Provider:
    def __init__(self, error: Exception | None = None, reasoning: str | None = None) -> None:
        self._error = error
        self._reasoning = reasoning

    def list_models(self) -> Any:  # pragma: no cover
        return ()

    def complete(self, **kwargs: Any) -> LLMResponse:
        if self._error is not None:
            raise self._error
        return LLMResponse(
            text="ESTIMATE bullish weight=0.3 return=+0.04 vol=0.30",
            model_id="m",
            finish_reason="stop",
            completion_tokens=40,
            reasoning_tokens=4000,
            reasoning_text=self._reasoning,
        )


class _Prompts:
    def render(self, *args: Any, **kwargs: Any) -> RenderedPrompt:  # pragma: no cover
        return PROMPT


def _agent(provider: _Provider, sink: _Sink) -> LLMAgent:
    return LLMAgent(
        provider=provider,
        model=MODEL,
        sampling=SamplingParams(temperature=0.7, max_tokens=12000),
        prompts=_Prompts(),
        trace=CountingTrace(sink),
        stage="analyst",
    )


# ---------------------------------------------------------------------------
# A failed call must still leave evidence
# ---------------------------------------------------------------------------
def test_an_exhausted_budget_is_recorded_before_it_is_raised() -> None:
    """ALLY's and ACGL's traces held a single `intake` event and nothing for the
    analyst, because the call that burned 12,000 tokens raised before the trace
    write. The item failed and the reason it failed was unrecoverable."""
    sink = _Sink()
    error = ModelBudgetExhaustedError("m", 12000, 11997, LOOP)
    with pytest.raises(ModelBudgetExhaustedError):
        _agent(_Provider(error=error), sink)._complete(PROMPT)
    assert len(sink.events) == 1
    assert sink.events[0]["stage"] == "analyst"


def test_the_recorded_event_carries_the_reasoning_that_ran_away() -> None:
    """The whole point: enough to run a redundancy analysis offline, with no
    inference and no contention with a running band."""
    sink = _Sink()
    with pytest.raises(ModelBudgetExhaustedError):
        _agent(_Provider(error=ModelBudgetExhaustedError("m", 12000, 11997, LOOP)), sink)._complete(
            PROMPT
        )
    data = sink.events[0]["data"]
    assert data["reasoning_text"] == LOOP
    assert data["reasoning_tokens"] == 11997
    assert data["finish_reason"] == "length"
    assert data["completion_tokens"] == 12000


def test_the_prompt_is_recorded_too_so_the_call_can_be_replayed() -> None:
    sink = _Sink()
    with pytest.raises(ModelBudgetExhaustedError):
        _agent(_Provider(error=ModelBudgetExhaustedError("m", 12000, 11997, LOOP)), sink)._complete(
            PROMPT
        )
    data = sink.events[0]["data"]
    assert data["messages"] == [{"role": "user", "content": "facts"}]
    assert data["sampling"]["max_tokens"] == 12000


def test_the_error_still_propagates_after_being_recorded() -> None:
    """Recording must not swallow it: the item still has to fail."""
    sink = _Sink()
    with pytest.raises(ModelBudgetExhaustedError, match="produced no answer"):
        _agent(_Provider(error=ModelBudgetExhaustedError("m", 12000, 11997)), sink)._complete(
            PROMPT
        )


def test_an_error_with_no_reasoning_text_records_an_empty_one() -> None:
    """A backend that names the field differently costs a missing diagnostic, never
    a wrong classification."""
    sink = _Sink()
    with pytest.raises(ModelBudgetExhaustedError):
        _agent(_Provider(error=ModelBudgetExhaustedError("m", 12000, 11997)), sink)._complete(
            PROMPT
        )
    assert sink.events[0]["data"]["reasoning_text"] == ""


# ---------------------------------------------------------------------------
# And a successful call records its reasoning too
# ---------------------------------------------------------------------------
def test_a_successful_call_records_its_reasoning() -> None:
    """The trace claims to hold "every prompt and every raw response". For a
    reasoning model most of the raw response was being discarded, so the successful
    distribution could be counted but never read against the failures."""
    sink = _Sink()
    _agent(_Provider(reasoning="First, revenue rose."), sink)._complete(PROMPT)
    assert sink.events[0]["data"]["reasoning_text"] == "First, revenue rose."


def test_a_model_that_reports_no_reasoning_records_none() -> None:
    sink = _Sink()
    _agent(_Provider(), sink)._complete(PROMPT)
    assert sink.events[0]["data"]["reasoning_text"] is None
