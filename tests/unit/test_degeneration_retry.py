"""The degeneration retry (ADR 0021).

Two corpus items failed intake at its 2,048-token cap. The tail was not a long
document — it was a loop: 757 lines of which 22 were unique, and 53 of which 21
were. Both completed normally when the same prompt was re-run under a frequency
penalty of 0.3, at 350 and 1,171 tokens.

The penalty is applied ONLY as a retry after a truncated first attempt. Measured on
three well-behaved items it also changes them — one nearly doubled in length,
another shrank a fifth — so applying it by default would perturb 354 items to
rescue 2. These tests hold that boundary: a first call never carries a penalty, and
a well-behaved item is never retried.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from mapf.agents.base import LLMAgent
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
    template_name="intake",
    template_version="v2",
    template_sha256="0" * 64,
    messages=(Message(role="user", content="a document"),),
)


class _Provider:
    """Returns `finishes` in order, recording the sampling of each call."""

    def __init__(self, *finishes: str) -> None:
        self._finishes = list(finishes)
        self.calls: list[SamplingParams] = []
        self.attempts: list[int] = []

    def list_models(self) -> Sequence[ModelInfo]:  # pragma: no cover
        return ()

    def complete(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(kwargs["sampling"])
        self.attempts.append(kwargs["attempt"])
        reason = self._finishes[min(len(self.calls) - 1, len(self._finishes) - 1)]
        return LLMResponse(text=f"answer {len(self.calls)}", model_id="m", finish_reason=reason)


class _Sink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


class _Prompts:
    def render(self, *args: Any, **kwargs: Any) -> RenderedPrompt:  # pragma: no cover
        return PROMPT


def _agent(provider: _Provider, penalty: float | None, trace: Any) -> LLMAgent:
    return LLMAgent(
        provider=provider,
        model=MODEL,
        sampling=SamplingParams(temperature=0.0, max_tokens=2048),
        prompts=_Prompts(),
        trace=trace,
        stage="intake",
        degeneration_penalty=penalty,
    )


def _call(agent: LLMAgent) -> LLMResponse:
    return agent._complete(PROMPT)


# ---------------------------------------------------------------------------
# When it fires, and when it must not
# ---------------------------------------------------------------------------
def test_a_completed_first_attempt_is_never_retried() -> None:
    """The 354 well-behaved items must reach the model exactly once, unpenalised.

    This is the whole reason the penalty is a retry rather than a default: at 0.3
    it changed every normal item measured.
    """
    provider = _Provider("stop")
    _call(_agent(provider, 0.3, CountingTrace(_Sink())))
    assert len(provider.calls) == 1
    assert provider.calls[0].frequency_penalty is None


def test_a_first_attempt_never_carries_the_penalty() -> None:
    provider = _Provider("length", "stop")
    _call(_agent(provider, 0.3, CountingTrace(_Sink())))
    assert provider.calls[0].frequency_penalty is None


def test_a_truncated_attempt_is_retried_once_under_the_penalty() -> None:
    provider = _Provider("length", "stop")
    response = _call(_agent(provider, 0.3, CountingTrace(_Sink())))
    assert len(provider.calls) == 2
    assert provider.calls[1].frequency_penalty == 0.3
    assert response.text == "answer 2"


def test_the_retry_changes_nothing_but_the_penalty() -> None:
    """A retry that also moved the temperature or the cap would confound the fix."""
    provider = _Provider("length", "stop")
    _call(_agent(provider, 0.3, CountingTrace(_Sink())))
    first, second = provider.calls
    assert second.model_dump(exclude={"frequency_penalty"}) == first.model_dump(
        exclude={"frequency_penalty"}
    )


def test_it_retries_once_and_not_twice() -> None:
    """A second identical loop is no evidence a third would differ, and the item
    still has to fail loudly rather than be ground at."""
    provider = _Provider("length", "length", "stop")
    _call(_agent(provider, 0.3, CountingTrace(_Sink())))
    assert len(provider.calls) == 2


def test_an_agent_with_no_penalty_configured_does_not_retry() -> None:
    """The analyst already samples at 0.7 and the structuralist decodes against a
    schema; neither gets the retry, so neither may be silently given one."""
    provider = _Provider("length", "stop")
    _call(_agent(provider, None, CountingTrace(_Sink())))
    assert len(provider.calls) == 1


def test_the_retry_takes_a_distinct_cache_slot() -> None:
    """Same prompt, same model. Without a distinct attempt index the retry could be
    served the looped response straight from the cache (ADR 0001)."""
    provider = _Provider("length", "stop")
    _call(_agent(provider, 0.3, CountingTrace(_Sink())))
    assert provider.attempts == [0, 1]


# ---------------------------------------------------------------------------
# What the record says afterwards
# ---------------------------------------------------------------------------
def test_a_rescued_item_is_no_longer_flagged_as_truncated() -> None:
    """The looped output is discarded and the prompt re-run, so nothing downstream
    ever sees the fragment — unlike a repair attempt, which is built from it."""
    trace = CountingTrace(_Sink())
    _call(_agent(_Provider("length", "stop"), 0.3, trace))
    assert trace.truncated_output == set()
    assert trace.degeneration_retries == {"intake"}


def test_a_retry_that_loops_again_stays_flagged() -> None:
    trace = CountingTrace(_Sink())
    _call(_agent(_Provider("length", "length"), 0.3, trace))
    assert trace.truncated_output == {"intake"}


def test_the_trace_records_the_sampling_that_produced_each_response() -> None:
    """Without this the trace cannot show which attempt carried the penalty, and a
    retry becomes unauditable from the artifact that exists to audit it."""
    sink = _Sink()
    _call(_agent(_Provider("length", "stop"), 0.3, CountingTrace(sink)))
    penalties = [event["data"]["sampling"]["frequency_penalty"] for event in sink.events]
    assert penalties == [None, 0.3]


def test_the_counting_trace_keeps_the_sampling_that_actually_ran() -> None:
    trace = CountingTrace(_Sink())
    _call(_agent(_Provider("length", "stop"), 0.3, trace))
    assert trace.sampling["intake"].frequency_penalty == 0.3


def test_an_ordinary_run_records_no_retry_and_no_penalty() -> None:
    trace = CountingTrace(_Sink())
    _call(_agent(_Provider("stop"), 0.3, trace))
    assert trace.degeneration_retries == set()
    assert trace.sampling["intake"].frequency_penalty is None


def test_both_attempts_reach_the_trace() -> None:
    """The looped output is discarded from the pipeline, not from the audit trail."""
    sink = _Sink()
    _call(_agent(_Provider("length", "stop"), 0.3, CountingTrace(sink)))
    assert [event["data"]["response"] for event in sink.events] == ["answer 1", "answer 2"]


# ---------------------------------------------------------------------------
# The penalty as a cache-key and wire concern
# ---------------------------------------------------------------------------
def test_the_penalty_is_part_of_the_cache_key() -> None:
    """A response produced under a penalty must never be served to a request
    without one — they are different samplers on the same prompt."""
    from mapf.providers.keys import request_key

    plain = SamplingParams(temperature=0.0, max_tokens=2048)
    penalised = plain.model_copy(update={"frequency_penalty": 0.3})
    assert request_key(model=MODEL, prompt=PROMPT, sampling=plain) != request_key(
        model=MODEL, prompt=PROMPT, sampling=penalised
    )


@pytest.mark.parametrize("bad", [-0.1, 2.1])
def test_the_penalty_is_bounded(bad: float) -> None:
    with pytest.raises(ValueError):
        SamplingParams(temperature=0.0, frequency_penalty=bad)


def test_the_retry_sampling_is_derived_not_configured_separately() -> None:
    """So a retry can never differ from its first attempt in anything but the
    penalty, however the agent was configured."""
    agent = _agent(_Provider("stop"), 0.6, CountingTrace(_Sink()))
    assert agent.retry_sampling.frequency_penalty == 0.6
    assert agent.retry_sampling.max_tokens == agent.sampling.max_tokens
    assert agent.retry_sampling.temperature == agent.sampling.temperature


def test_only_intake_carries_a_penalty_in_the_shipped_configuration() -> None:
    """The corpus-wide claim: 354 items sample exactly as they always did."""
    from mapf.settings.loader import load

    models = load().models
    assert models.intake.degeneration_penalty == 0.3
    assert models.analyst.degeneration_penalty is None
    assert models.structuralist.degeneration_penalty is None
