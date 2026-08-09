"""Agent -> configured alias -> resolved model.

Why a registry at all: `CLAUDE.md` §4 says an agent is a contract, not a model.
The agents therefore know their *name* and nothing about weights; this module is
what turns "the structuralist" into a concrete `ModelInfo` and a `SamplingParams`,
and it is the only place that mapping exists. Swapping a model is a config edit
because the mapping is data, not code.

Resolution is **exact-match only**, with a case-insensitive second pass. There is
deliberately no fuzzy matching: a near-miss that silently selects different
weights produces a complete, valid, wrong forecast, and would invalidate every
cached result under that fingerprint. Failing with the list of what the server
actually has is the more useful answer (`CLAUDE.md` §5).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict

from mapf.core.errors import ModelNotAvailableError
from mapf.core.ports import ModelInfo, SamplingParams
from mapf.settings.loader import ModelSettings, ModelsSettings

AgentName = Literal["intake", "analyst", "structuralist"]

AGENT_NAMES: tuple[AgentName, ...] = get_args(AgentName)
"""Pipeline order. Also the order models are swapped in and out of memory."""


class ModelSpec(BaseModel):
    """Everything an agent needs about its model, and nothing about the server."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: AgentName
    alias: str
    sampling: SamplingParams


def _to_spec(agent: AgentName, configured: ModelSettings) -> ModelSpec:
    return ModelSpec(
        agent=agent,
        alias=configured.alias,
        sampling=SamplingParams(
            temperature=configured.temperature,
            seed=configured.seed,
            top_p=configured.top_p,
            max_tokens=configured.max_tokens,
        ),
    )


class ModelRegistry:
    """Immutable view over the configured models."""

    def __init__(self, models: ModelsSettings) -> None:
        self._specs: dict[AgentName, ModelSpec] = {
            agent: _to_spec(agent, getattr(models, agent)) for agent in AGENT_NAMES
        }

    @property
    def specs(self) -> tuple[ModelSpec, ...]:
        return tuple(self._specs[agent] for agent in AGENT_NAMES)

    def spec(self, agent: AgentName) -> ModelSpec:
        return self._specs[agent]

    def resolve(self, agent: AgentName, available: Sequence[ModelInfo]) -> ModelInfo:
        """Find the loaded model backing `agent`, or fail with what is available.

        Model ids are read from the server rather than hardcoded, because the same
        weights are named differently by different backends. The alias in config
        is the adaptation point.
        """
        alias = self._specs[agent].alias
        for info in available:
            if info.id == alias:
                return info
        folded = alias.casefold()
        for info in available:
            if info.id.casefold() == folded:
                return info
        raise ModelNotAvailableError(alias, [info.id for info in available])

    def resolve_all(self, available: Sequence[ModelInfo]) -> Mapping[AgentName, ModelInfo]:
        """Resolve every agent up front.

        `map health` reports all missing models at once rather than one per run:
        discovering the third missing alias after two model swaps is a slow way to
        learn something a single startup check could have said immediately.
        """
        resolved: dict[AgentName, ModelInfo] = {}
        missing: list[ModelNotAvailableError] = []
        for agent in AGENT_NAMES:
            try:
                resolved[agent] = self.resolve(agent, available)
            except ModelNotAvailableError as err:
                missing.append(err)
        if missing:
            raise ModelNotAvailableError(
                ", ".join(err.alias for err in missing),
                [info.id for info in available],
            )
        return resolved
