"""The agent contract and the plumbing all three share.

`Agent` is deliberately tiny. An agent is `(input) -> (output)`; everything else —
which model, which sampling parameters, whether a cache sits in front of the
provider — is injected and invisible from here. If a new model release ever forces
an edit to a module in this package, the abstraction has leaked (`CLAUDE.md` §4).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, Protocol, TypeVar

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
    ) -> None:
        self._template = template or self.TEMPLATE
        self._version = version or self.VERSION
        self._provider = provider
        self._model = model
        self._sampling = sampling
        self._prompts = prompts
        self._trace = trace
        self._stage = stage

    @property
    def model(self) -> ModelInfo:
        """Read-only. The pipeline assembles provenance it did not choose."""
        return self._model

    @property
    def sampling(self) -> SamplingParams:
        return self._sampling

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

    def _complete(
        self,
        prompt: RenderedPrompt,
        *,
        json_schema: Mapping[str, Any] | None = None,
        attempt: int = 0,
    ) -> LLMResponse:
        response = self._provider.complete(
            model=self._model,
            prompt=prompt,
            sampling=self._sampling,
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
