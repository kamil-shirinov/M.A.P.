"""Configuration and the model registry.

The public names are re-exported here so callers write
`from mapf.settings import Settings, ModelSpec` with no stutter at any call site,
and the internal file layout stays free to change without touching importers.

This is the one package in `mapf` where re-exporting is right: `core` deliberately
does not, because there the *location* of a type is part of what the architecture
is arguing.
"""

from mapf.settings.loader import (
    DEFAULT_CONFIG_FILES,
    DETERMINISTIC_AGENTS,
    PLACEHOLDER_MARKER,
    CacheSettings,
    DataSettings,
    InferenceSettings,
    ModelSettings,
    ModelsSettings,
    NewsSettings,
    PathsSettings,
    SecSettings,
    Settings,
    load,
)
from mapf.settings.registry import AGENT_NAMES, AgentName, ModelRegistry, ModelSpec

__all__ = [
    "AGENT_NAMES",
    "DEFAULT_CONFIG_FILES",
    "DETERMINISTIC_AGENTS",
    "PLACEHOLDER_MARKER",
    "AgentName",
    "CacheSettings",
    "DataSettings",
    "InferenceSettings",
    "ModelRegistry",
    "ModelSettings",
    "ModelSpec",
    "ModelsSettings",
    "NewsSettings",
    "PathsSettings",
    "SecSettings",
    "Settings",
    "load",
]
