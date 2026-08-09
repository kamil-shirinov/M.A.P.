"""Disk cache as an `LLMProvider` decorator.

A decorator rather than a helper the agents call: agents stay cache-unaware, the
logic exists once instead of three times, and no agent is coupled to a disk
layout. Because it implements the same Protocol, `bootstrap` can wrap or unwrap it
without any layer above noticing.

This is infrastructure, not an optimisation (`CLAUDE.md` §6). A cold run pays
three model swaps and 8-15 tok/s on a 12B; without a cache, backtesting is not
slow but impossible. It is also what DoD criterion 5 measures.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import structlog

from mapf.core.ports import (
    LLMProvider,
    LLMResponse,
    ModelInfo,
    RenderedPrompt,
    SamplingParams,
)
from mapf.providers.keys import request_key

_logger = structlog.get_logger(__name__)


class CachingProvider:
    """Wraps any `LLMProvider` with a content-addressed disk cache."""

    def __init__(self, inner: LLMProvider, cache_dir: Path) -> None:
        self._inner = inner
        self._cache_dir = cache_dir

    def list_models(self) -> Sequence[ModelInfo]:
        """Never cached. Discovery is how a re-pointed tag gets noticed at all —
        caching it would hide the change the fingerprint exists to catch."""
        return self._inner.list_models()

    def complete(
        self,
        *,
        model: ModelInfo,
        prompt: RenderedPrompt,
        sampling: SamplingParams,
        json_schema: Mapping[str, Any] | None = None,
        attempt: int = 0,
    ) -> LLMResponse:
        key = request_key(
            model=model,
            prompt=prompt,
            sampling=sampling,
            json_schema=json_schema,
            attempt=attempt,
        )
        path = self._path(model.fingerprint, key)

        cached = self._read(path)
        if cached is not None:
            # Flagged, not silent: the trace must show a hit, or the second run
            # looks like it never happened and criterion 5 is unauditable.
            return cached.model_copy(update={"cache_hit": True})

        response = self._inner.complete(
            model=model,
            prompt=prompt,
            sampling=sampling,
            json_schema=json_schema,
            attempt=attempt,
        )
        self._write(path, response)
        return response

    # -- storage -----------------------------------------------------------
    def _path(self, fingerprint: str, key: str) -> Path:
        # Namespaced by fingerprint (ADR 0001): different weights cannot collide,
        # and a stale namespace can be deleted wholesale. The two-character shard
        # keeps directory listings usable after a few thousand entries.
        return self._cache_dir / fingerprint / key[:2] / f"{key}.json"

    def _read(self, path: Path) -> LLMResponse | None:
        if not path.is_file():
            return None
        try:
            return LLMResponse.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            # A corrupt entry is a miss, not a crash. Half-written files are what a
            # SIGKILL mid-write leaves behind, and losing a run to one would be a
            # worse failure than recomputing it.
            _logger.warning("cache_entry_unreadable", path=str(path), error=str(err))
            return None

    def _write(self, path: Path, response: LLMResponse) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: an interrupted write leaves a temp file rather than a
        # truncated cache entry that would later read as a valid short response.
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
        ) as handle:
            handle.write(response.model_dump_json())
            temp_path = Path(handle.name)
        temp_path.replace(path)
