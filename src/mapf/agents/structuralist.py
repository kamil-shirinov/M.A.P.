"""Agent 3 — narrative to schema, with the repair loop.

The loop lives here rather than in the validator or the pipeline. Not in the
validator, because a validator that retries is no longer a validator. Not in the
pipeline, because how an agent meets its contract is the agent's business — the
pipeline asks for a `ScenarioSet` and either gets one or gets an exception.

Why a loop is needed at all: constrained decoding makes an invalid *shape*
unreachable, but `ScenarioSet`'s two invariants — weights summing to one, and
`bearish < base_case < bullish` — span fields, and no JSON Schema can express
that (ADR 0002). They are exactly the failures the model can still produce, and
exactly what this loop answers.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import ValidationError

from mapf.agents.base import LLMAgent
from mapf.core.errors import ForecastRepairExhausted
from mapf.core.models import DomainModel, ScenarioNarrative, ScenarioSet, TrustedText
from mapf.core.ports import (
    LLMProvider,
    ModelInfo,
    PromptStore,
    RenderedPrompt,
    SamplingParams,
    Trace,
)
from mapf.core.quarantine import quarantine
from mapf.core.schema import decode_schema


class StructuralistRequest(DomainModel):
    narrative: ScenarioNarrative


def _format_errors(error: ValidationError) -> tuple[str, ...]:
    """Render validation failures as instructions the model can act on.

    **Only `loc` and `msg`.** Pydantic's error dicts also carry `input` — the
    offending value — and that value is model output derived from untrusted news.
    Feeding it back verbatim would re-inject exactly what the quarantine removed,
    through a slot we control and would have no reason to sanitise (ADR 0005).
    """
    rendered: list[str] = []
    for detail in error.errors():
        location = ".".join(str(part) for part in detail["loc"]) or "(root)"
        rendered.append(f"- {location}: {detail['msg']}")
    return tuple(rendered)


class StructuralistAgent(LLMAgent):
    """`StructuralistRequest -> ScenarioSet`."""

    TEMPLATE = "structuralist"
    REPAIR_TEMPLATE: ClassVar[str] = "structuralist_repair"

    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: ModelInfo,
        sampling: SamplingParams,
        prompts: PromptStore,
        trace: Trace,
        stage: str,
        max_attempts: int,
        template: str | None = None,
        version: str | None = None,
        repair_template: str | None = None,
        context_tokens: int | None = None,
        upstream: str | None = None,
        degeneration_penalty: float | None = None,
    ) -> None:
        super().__init__(
            provider=provider,
            model=model,
            sampling=sampling,
            prompts=prompts,
            trace=trace,
            stage=stage,
            template=template,
            version=version,
            context_tokens=context_tokens,
            upstream=upstream,
            degeneration_penalty=degeneration_penalty,
        )
        self._repair_template = repair_template or self.REPAIR_TEMPLATE
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")
        self._max_attempts = max_attempts

    def run(self, request: StructuralistRequest, /) -> ScenarioSet:
        schema = decode_schema(ScenarioSet)
        errors: tuple[str, ...] = ()
        last_response = ""

        for attempt in range(self._max_attempts):
            prompt = self._prompt_for(attempt, request, last_response, errors)
            # `attempt` reaches the provider only to namespace the cache. When the
            # same errors recur — the common case — attempt 3's prompt renders
            # byte-identical to attempt 2's, and without the index it would hit the
            # cache and replay a known failure without calling the model (ADR 0001).
            response = self._complete(prompt, json_schema=schema, attempt=attempt)
            last_response = response.text

            try:
                return ScenarioSet.model_validate_json(response.text)
            except ValidationError as err:
                errors = _format_errors(err)
                self._trace.record(
                    stage=f"{self._stage}.validation_failed",
                    attempt=attempt,
                    data={"errors": list(errors), "response": response.text},
                )

        # Never a coerced or partial object. A forecast patched into validity by the
        # pipeline is not the model's forecast, and scoring it in Phase 2 would
        # measure the patch.
        raise ForecastRepairExhausted(self._max_attempts, errors, last_response)

    def _prompt_for(
        self,
        attempt: int,
        request: StructuralistRequest,
        last_response: str,
        errors: tuple[str, ...],
    ) -> RenderedPrompt:
        narrative = quarantine(request.narrative.text)
        if attempt == 0:
            return self._render(self._template, self._version, untrusted={"narrative": narrative})
        return self._render(
            self._repair_template,
            self._version,
            trusted={
                "attempt": TrustedText(str(attempt + 1)),
                # Trusted because it is built from field paths and pydantic's own
                # messages — never from the rejected input.
                "validation_errors": TrustedText("\n".join(errors)),
            },
            untrusted={
                "narrative": narrative,
                # The model's own previous output is still derived from untrusted
                # news, so it is quarantined on the way back in.
                "previous_output": quarantine(last_response),
            },
        )
