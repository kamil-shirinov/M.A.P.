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

from mapf.core.errors import ConfigurationError, DeterminismPolicyError, PlaceholderConfigError

_logger = structlog.get_logger(__name__)

DEFAULT_CONFIG_FILES: tuple[Path, ...] = (
    Path("config/default.toml"),
    Path("config/local.toml"),  # optional, gitignored, machine-specific
)

PLACEHOLDER_MARKER = "REPLACE_ME"

# Agents whose output must be reproducible (CLAUDE.md §6).
DETERMINISTIC_AGENTS: tuple[str, ...] = ("intake", "structuralist")

_SEC_USER_AGENT_HINT = (
    "SEC EDGAR returns 403 and blocks the IP for about ten minutes without a "
    "descriptive User-Agent carrying a name and a contact email address. Set "
    "MAP_DATA__SEC__USER_AGENT, or edit data.sec.user_agent in config/default.toml, "
    "to something of the form 'Jane Doe jane@example.com M.A.P. research tool'."
)


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


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


class ModelSettings(_Section):
    alias: str = Field(min_length=1)
    temperature: float = Field(ge=0.0, le=2.0)
    seed: int | None = None
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=1)


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


class CacheSettings(_Section):
    llm_dir: Path
    price_dir: Path


class SecSettings(_Section):
    user_agent: str = Field(min_length=1)
    requests_per_second: float = Field(gt=0.0, le=10.0)
    tickers_url: str = Field(min_length=1)
    symbols_db: Path
    refresh_days: int = Field(ge=1)

    @model_validator(mode="after")
    def _reject_unusable_user_agent(self) -> Self:
        """Fail at startup rather than as a 403 and a ten-minute block mid-download.

        Raises a typed `ConfigurationError` subclass rather than a `ValidationError`
        on purpose: this is a policy failure with one specific remedy, and the
        remedy should be the whole message rather than one line inside a blob.
        """
        agent = self.user_agent.strip()
        if PLACEHOLDER_MARKER in agent:
            raise PlaceholderConfigError(
                "data.sec.user_agent", self.user_agent, _SEC_USER_AGENT_HINT
            )
        if "@" not in agent:
            raise ConfigurationError(
                f"config key 'data.sec.user_agent' has no contact address: {self.user_agent!r}. "
                + _SEC_USER_AGENT_HINT
            )
        return self


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
    cache: CacheSettings
    data: DataSettings
    news: NewsSettings
    paths: PathsSettings

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
