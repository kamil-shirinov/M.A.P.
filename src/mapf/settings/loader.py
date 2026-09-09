"""Typed configuration, loaded from TOML with an environment overlay.

Precedence is **environment > file**, which is inverted from pydantic-settings'
default (where init values win). That is deliberate: the file is the committed
baseline and the environment is the per-machine override, so
`MAP_DATA__SEC__USER_AGENT` must beat whatever `config/default.toml` says. The
inversion lives in one readable place, `settings_customise_sources`.

The TOML itself is read with stdlib `tomllib` rather than a settings source, so
that `load()` can be pointed at any file — which is what makes the tests in this
module work with no filesystem assumptions and no network. pydantic-settings is
still doing the work that matters: parsing `MAP_`-prefixed, `__`-nested
environment variables into a nested structure and coercing them to the declared
types.

This module names a backend vendor nowhere. `config/default.toml` is the only
file permitted to (`CLAUDE.md` §3).
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, Self

import structlog
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from mapf.core.errors import (
    ChainBudgetError,
    ConfigurationError,
    DeterminismPolicyError,
    UnreachableContextBudgetError,
    UnreachableTokenBudgetError,
)
from mapf.core.tokens import PROMPT_OVERHEAD, generation_reserve

_logger = structlog.get_logger(__name__)

DEFAULT_CONFIG_FILES: tuple[Path, ...] = (
    Path("config/default.toml"),
    Path("config/local.toml"),  # optional, gitignored, machine-specific
)

# Agents whose output must be reproducible (CLAUDE.md §6).
DETERMINISTIC_AGENTS: tuple[str, ...] = ("intake", "structuralist")


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# No prompt is empty; a budget that leaves less than this is unreachable in
# practice even when the arithmetic technically permits it.
_MIN_PROMPT_TOKENS = 512


class InferenceSettings(_Section):
    base_url: str = Field(min_length=1)
    # Connect and read are separate on purpose, and it is not a detail. The backend
    # loads weights on demand on 16 GB, so the first call after a model swap can sit
    # for 30 s or more before a single token arrives. One combined timeout forces a
    # choice between "fails constantly on a cold load" and "cannot tell a dead server
    # from a loading one" — see ADR 0008.
    connect_timeout_s: float = Field(gt=0.0)
    read_timeout_s: float = Field(gt=0.0)
    max_repair_attempts: int = Field(ge=1, le=10)

    min_tokens_per_second: float = Field(default=10.0, gt=0.0)
    """Slowest generation rate this machine is expected to sustain.

    **A hardware assumption, stated so it can be corrected.** On the reference M1
    (16 GB) a 12B at Q4 runs at roughly 10-15 tok/s, so 10 is the pessimistic end.
    It exists only to couple `max_tokens` to `read_timeout_s`, which are otherwise
    set independently and mean nothing to each other. Someone on faster or slower
    hardware needs to change this, and needs to know the constraint exists.
    """

    budget_margin: float = Field(default=0.8, gt=0.0, le=1.0)
    """Fraction of the read timeout a full token budget may consume.

    Not 1.0: prompt processing, a cold model load and the network all take time the
    generation rate does not account for.
    """


class ModelSettings(_Section):
    alias: str = Field(min_length=1)
    temperature: float = Field(ge=0.0, le=2.0)
    seed: int | None = None
    # The server's context window for this agent. Configured here so it can be
    # frozen with a corpus and checked before a run, but never trusted: it is a
    # server-side setting this file cannot enforce, so the pre-flight probes the
    # server for the real value and refuses on disagreement (ADR 0020 §4).
    context_tokens: int = Field(default=8192, ge=512)
    # What this agent can hand *downstream*, which for a reasoning model is far
    # less than `max_tokens`: the analyst spends most of a 12,000-token budget on
    # reasoning that never leaves the model — 5,329 reasoning against 565 of
    # visible narrative in one measured run. Defaults to `max_tokens`, which is
    # correct for an agent that emits everything it generates. It is a declared
    # bound, and the pre-dispatch assertion in `agents.base` is what enforces it.
    max_visible_tokens: int | None = Field(default=None, ge=1)

    @property
    def visible_budget(self) -> int | None:
        return self.max_visible_tokens if self.max_visible_tokens is not None else self.max_tokens

    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=1)
    # Applied only when this agent stops at its cap, and only for one retry
    # (ADR 0021). Unset means no retry: the item fails on a truncated output
    # instead, which is the right behaviour for an agent whose output is schema-
    # constrained or already sampled above zero.
    degeneration_penalty: float | None = Field(default=None, ge=0.0, le=2.0)


class ModelsSettings(_Section):
    intake: ModelSettings
    analyst: ModelSettings
    structuralist: ModelSettings

    allow_nondeterministic: bool = False
    """Deliberate, auditable escape hatch from the `temperature=0` rule (ADR 0007).

    A hard block invites someone in a hurry to delete the validator, which leaves no
    trace at all. An override that must be set on purpose, warns at startup, and is
    stamped into the run manifest keeps the run *marked* instead of silently ordinary.
    """

    @model_validator(mode="after")
    def _enforce_determinism(self) -> Self:
        offenders = [
            (agent, temperature)
            for agent in DETERMINISTIC_AGENTS
            if (temperature := getattr(self, agent).temperature) != 0.0
        ]
        if not offenders:
            return self
        if not self.allow_nondeterministic:
            agent, temperature = offenders[0]
            raise DeterminismPolicyError(agent, temperature)
        _logger.warning(
            "determinism_override_active",
            agents=[agent for agent, _ in offenders],
            temperatures=[temperature for _, temperature in offenders],
            consequence="runs are not reproducible; the manifest will record this",
        )
        return self


class PromptsSettings(_Section):
    """Which prompt version each agent uses.

    Config rather than code, because `CLAUDE.md` §4 says versioned prompts exist so
    per-model variants can coexist without touching logic. Until the agents took
    `template`/`version` as parameters that was not actually true — the name was a
    module constant and a variant meant editing `mapf.agents`.
    """

    intake: str = "v1"
    analyst: str = "v1"
    structuralist: str = "v1"


class CacheSettings(_Section):
    llm_dir: Path
    price_dir: Path
    earnings_dir: Path = Path("var/earnings")


class SecSettings(_Section):
    user_agent: str = Field(min_length=1)
    requests_per_second: float = Field(gt=0.0, le=10.0)
    tickers_url: str = Field(min_length=1)
    symbols_db: Path
    refresh_days: int = Field(ge=1)

    # NOT validated here. The placeholder check is a SEC network policy and lives
    # with the three adapters that send the header (`mapf.data.sec`): validating it
    # at settings load made every command inherit a guard for a credential most of
    # them never use, and made the offline test suite depend on operator config.


class DataSettings(_Section):
    provider_order: tuple[str, ...] = Field(min_length=1)
    adjustment: Literal["split_adjusted"]
    history_days: int = Field(ge=1)
    sec: SecSettings


class NewsSettings(_Section):
    dir: Path
    rss_urls: tuple[str, ...] = ()


class PathsSettings(_Section):
    runs_dir: Path


class Settings(BaseSettings):
    """The whole configuration. Frozen: nothing reconfigures itself mid-run."""

    model_config = SettingsConfigDict(
        env_prefix="MAP_",
        env_nested_delimiter="__",
        extra="forbid",
        frozen=True,
    )

    inference: InferenceSettings
    models: ModelsSettings
    prompts: PromptsSettings = PromptsSettings()
    cache: CacheSettings
    data: DataSettings
    news: NewsSettings
    paths: PathsSettings

    @model_validator(mode="after")
    def _budgets_fit_their_context(self) -> Self:
        """Generation shares the context window with the prompt.

        A `max_tokens` at or above `context_tokens` leaves no room for a prompt, so
        the budget can never be spent. The model stops at the context ceiling and
        reports exhaustion, which is indistinguishable from a genuinely long
        reasoning chain unless you happen to know both numbers. Checked here so
        they cannot be set independently into contradiction again.
        """
        for agent in ("intake", "analyst", "structuralist"):
            spec = getattr(self.models, agent)
            if spec.max_tokens is None:
                continue
            # A prompt of at least a few hundred tokens always exists; requiring
            # strict headroom rather than mere inequality keeps the check honest.
            if spec.max_tokens + _MIN_PROMPT_TOKENS > spec.context_tokens:
                raise UnreachableContextBudgetError(agent, spec.max_tokens, spec.context_tokens)
        return self

    @model_validator(mode="after")
    def _each_output_fits_the_next_input(self) -> Self:
        """Every agent's maximum output must fit the next agent's input window.

        Each budget was previously checked against its own context and the chain
        between them against nothing. Intake then emitted ~20,000 tokens from a
        12,500-token document — it expanded rather than compressed — and the
        analyst rejected the resulting 22,368-token prompt. Both agents were
        individually valid; the pipeline they formed was not.
        """
        for upstream, downstream in (("intake", "analyst"), ("analyst", "structuralist")):
            produced = getattr(self.models, upstream).visible_budget
            if produced is None:
                # Unbounded output cannot be checked here. The pre-dispatch
                # assertion still catches it, but at run time rather than startup.
                continue
            spec = getattr(self.models, downstream)
            overhead = PROMPT_OVERHEAD.get(downstream, 800)
            reserved = generation_reserve(spec.max_tokens)
            if produced + overhead + reserved > spec.context_tokens:
                raise ChainBudgetError(
                    upstream, downstream, produced, overhead, reserved, spec.context_tokens
                )
        return self

    @model_validator(mode="after")
    def _token_budgets_are_reachable(self) -> Self:
        """`max_tokens` and `read_timeout_s` are set independently; the hardware
        couples them.

        A budget the model cannot finish spending before the read timeout fires is
        not a budget — a run that reached it would fail as a timeout and send the
        reader hunting for a cold model load that never happened. Checked at
        startup so the two cannot drift apart in a later edit.
        """
        allowed = self.inference.read_timeout_s * self.inference.budget_margin
        for agent in ("intake", "analyst", "structuralist"):
            configured = getattr(self.models, agent).max_tokens
            if configured is None:
                continue
            if configured / self.inference.min_tokens_per_second > allowed:
                raise UnreachableTokenBudgetError(
                    agent,
                    configured,
                    self.inference.read_timeout_s,
                    self.inference.min_tokens_per_second,
                    self.inference.budget_margin,
                )
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Environment beats file.

        `load()` passes the parsed TOML as init values, so putting `env_settings`
        ahead of `init_settings` is what makes `MAP_*` override the committed
        baseline. Highest precedence first.
        """
        return (env_settings, dotenv_settings, init_settings, file_secret_settings)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge `overlay` into `base`, table by table.

    A shallow update would let `config/local.toml` overriding one SEC key silently
    delete every other key in that table.
    """
    for key, value in overlay.items():
        existing = base.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            base[key] = _deep_merge(dict(existing), value)
        else:
            base[key] = value
    return base


def load(config_files: Sequence[Path] | None = None) -> Settings:
    """Read the TOML baseline, then let the environment override it.

    Missing files are skipped rather than fatal — `config/local.toml` is optional
    by design — but if *no* file yielded anything and the environment does not
    supply a complete configuration, the resulting error should say so plainly
    rather than surfacing as six missing-field errors.
    """
    files = DEFAULT_CONFIG_FILES if config_files is None else tuple(config_files)
    merged: dict[str, Any] = {}
    found: list[Path] = []
    for path in files:
        if not path.is_file():
            continue
        merged = _deep_merge(merged, tomllib.loads(path.read_text(encoding="utf-8")))
        found.append(path)

    if not found and not merged:
        searched = ", ".join(str(path) for path in files)
        raise ConfigurationError(
            f"no configuration file found (searched: {searched}). "
            "Run from the repository root, or pass an explicit path."
        )

    return Settings(**merged)
