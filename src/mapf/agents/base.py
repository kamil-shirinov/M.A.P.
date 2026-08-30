"""The agent contract and the plumbing all three share.

`Agent` is deliberately tiny. An agent is `(input) -> (output)`; everything else —
which model, which sampling parameters, whether a cache sits in front of the
provider — is injected and invisible from here. If a new model release ever forces
an edit to a module in this package, the abstraction has leaked (`CLAUDE.md` §4).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, Protocol, TypeVar

from mapf.core.errors import PromptTooLargeError
from mapf.core.models import TrustedText
from mapf.core.ports import (
    LLMProvider,
    LLMResponse,
    ModelInfo,
    PromptStore,
    RenderedPrompt,
    SamplingParams,
    Trace,
)
from mapf.core.quarantine import QuarantinedText
from mapf.core.tokens import estimate_tokens, prompt_allowance

InT_contra = TypeVar("InT_contra", contravariant=True)
OutT_co = TypeVar("OutT_co", covariant=True)


class Agent(Protocol[InT_contra, OutT_co]):
    """One step of the pipeline, as a type."""

    def run(self, request: InT_contra, /) -> OutT_co: ...


class LLMAgent:
    """Shared base: render a template, call the model, record the exchange.

    `template` and `version` are constructor parameters with class-level defaults,
    not module constants. They were constants, and that was an abstraction leak:
    `CLAUDE.md` §4 says prompts are versioned precisely so per-model variants can
    coexist "without touching logic", and with the name baked into the module the
    only way to point an agent at a different prompt was to edit this package.

    Holds no model knowledge beyond the `ModelInfo` it was handed, and no cache
    knowledge at all — a `CachingProvider` is indistinguishable from a bare one
    through the `LLMProvider` Protocol, which is exactly the intent.
    """

    TEMPLATE: ClassVar[str] = ""
    VERSION: ClassVar[str] = "v1"

    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: ModelInfo,
        sampling: SamplingParams,
        prompts: PromptStore,
        trace: Trace,
        stage: str,
        template: str | None = None,
        version: str | None = None,
        context_tokens: int | None = None,
        upstream: str | None = None,
        degeneration_penalty: float | None = None,
    ) -> None:
        self._template = template or self.TEMPLATE
        self._version = version or self.VERSION
        self._provider = provider
        self._model = model
        self._sampling = sampling
        self._prompts = prompts
        self._trace = trace
        self._stage = stage
        self._context_tokens = context_tokens
        self._upstream = upstream
        self._degeneration_penalty = degeneration_penalty

    @property
    def model(self) -> ModelInfo:
        """Read-only. The pipeline assembles provenance it did not choose."""
        return self._model

    @property
    def sampling(self) -> SamplingParams:
        return self._sampling

    @property
    def retry_sampling(self) -> SamplingParams:
        """The configured parameters plus the degeneration penalty (ADR 0021).

        Derived rather than configured separately, so a retry can never silently
        differ from the first attempt in anything but the penalty.
        """
        return self._sampling.model_copy(update={"frequency_penalty": self._degeneration_penalty})

    @property
    def stage(self) -> str:
        return self._stage

    @property
    def template(self) -> str:
        return self._template

    @property
    def version(self) -> str:
        return self._version

    def _render(
        self,
        template: str,
        version: str,
        *,
        trusted: Mapping[str, TrustedText] | None = None,
        untrusted: Mapping[str, QuarantinedText] | None = None,
    ) -> RenderedPrompt:
        return self._prompts.render(template, version, trusted=trusted, untrusted=untrusted)

    def _assert_fits(self, prompt: RenderedPrompt, sampling: SamplingParams) -> None:
        """Refuse an oversized prompt here, where its origin is still known.

        The server answers an over-long request with an HTTP 400 that says only
        that something did not fit — not which agent produced the payload, nor how
        large it was. Both are known at this point and unrecoverable afterwards.
        """
        if self._context_tokens is None:
            return
        tokens = estimate_tokens(sum(len(m.content) for m in prompt.messages))
        allowance = prompt_allowance(self._context_tokens, sampling.max_tokens)
        if tokens > allowance:
            raise PromptTooLargeError(
                self._stage, self._upstream, tokens, allowance, self._context_tokens
            )

    def _complete(
        self,
        prompt: RenderedPrompt,
        *,
        json_schema: Mapping[str, Any] | None = None,
        attempt: int = 0,
    ) -> LLMResponse:
        """One call, plus one degeneration retry where a penalty is configured.

        Stopping at the token cap is a decoding loop far more often than genuine
        length: the two observed cases were 97% and 60% repeated lines, and both
        completed normally under a frequency penalty (ADR 0021). One retry, then
        the caller's truncation check fails the item — a second identical loop is
        no evidence a third would differ, and the penalty is a deviation from the
        corpus-wide sampling that must stay rare enough to report.
        """
        response = self._dispatch(prompt, self._sampling, json_schema, attempt)
        if self._degeneration_penalty is None or response.finish_reason != "length":
            return response
        return self._dispatch(prompt, self.retry_sampling, json_schema, attempt + 1)

    def _dispatch(
        self,
        prompt: RenderedPrompt,
        sampling: SamplingParams,
        json_schema: Mapping[str, Any] | None,
        attempt: int,
    ) -> LLMResponse:
        self._assert_fits(prompt, sampling)
        response = self._provider.complete(
            model=self._model,
            prompt=prompt,
            sampling=sampling,
            json_schema=json_schema,
            attempt=attempt,
        )
        # Every prompt and every raw response, cache hits included (`CLAUDE.md` §6).
        # Skipping hits would leave the second run's trace empty and make DoD
        # criterion 5 unauditable.
        self._trace.record(
            stage=self._stage,
            attempt=attempt,
            cache_hit=response.cache_hit,
            data={
                "template": f"{prompt.template_name}.{prompt.template_version}",
                "template_sha256": prompt.template_sha256,
                # The sampling that produced THIS response, not the agent's
                # configured sampling. A degeneration retry differs from its own
                # first attempt, and without this the trace cannot show which.
                "sampling": sampling.model_dump(),
                "messages": [message.model_dump() for message in prompt.messages],
                "response": response.text,
                "model_id": response.model_id,
                "finish_reason": response.finish_reason,
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "reasoning_tokens": response.reasoning_tokens,
            },
        )
        return response
