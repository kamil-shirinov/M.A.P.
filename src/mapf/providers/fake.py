"""Fixture-replaying provider.

Ships in `src/`, not `tests/`, deliberately: the CLI must be able to run with no
inference server at all, and a provider that only exists under pytest cannot do
that. It is also what makes DoD criterion 6 structural rather than aspirational —
`import-linter` already guarantees agents cannot reach `httpx`, and this is the
implementation they get instead.

Deterministic and inspectable are both requirements, not niceties. Lookup is by
the same `request_key` the cache uses, so a fixture recorded during one run is
found by the next. `consumed` records which fixture each call actually read, so a
failing test can be traced to the recording that produced it rather than guessed
at.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mapf.core.errors import FixtureNotFoundError, InferenceProtocolError
from mapf.core.ports import (
    LLMProvider,
    LLMResponse,
    ModelInfo,
    RenderedPrompt,
    SamplingParams,
)
from mapf.providers.keys import request_key

DEFAULT_FIXTURE_DIR = Path("tests/fixtures/llm")

MODELS_FIXTURE = "models.json"
"""Optional. Holds the `ModelInfo` list `list_models()` should replay."""


class FixtureUse(BaseModel):
    """One recorded consumption, for after-the-fact inspection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(min_length=1)
    path: Path
    model_id: str = Field(min_length=1)
    attempt: int = Field(ge=0)


class FakeProvider:
    """Replays recorded responses. Never touches the network."""

    def __init__(
        self,
        fixture_dir: Path = DEFAULT_FIXTURE_DIR,
        *,
        models: Sequence[ModelInfo] = (),
    ) -> None:
        self._fixture_dir = fixture_dir
        self._models = tuple(models)
        self._consumed: list[FixtureUse] = []

    @property
    def consumed(self) -> tuple[FixtureUse, ...]:
        """Every fixture read so far, in order."""
        return tuple(self._consumed)

    @property
    def fixture_dir(self) -> Path:
        return self._fixture_dir

    def list_models(self) -> Sequence[ModelInfo]:
        """Injected models win; otherwise replay `models.json` if it exists.

        Injection is for tests that care about one model. The file is for running
        the CLI offline, where the fixture set has to stand in for a whole server.
        """
        if self._models:
            return self._models
        path = self._fixture_dir / MODELS_FIXTURE
        if not path.is_file():
            return ()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as err:
            raise InferenceProtocolError(f"{path} is not valid JSON: {err}") from err
        if not isinstance(raw, list):
            raise InferenceProtocolError(f"{path} must hold a list of models")
        return tuple(ModelInfo.model_validate(entry) for entry in raw)

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
        path = self._fixture_dir / f"{key}.json"
        if not path.is_file():
            raise FixtureNotFoundError(key, str(self._fixture_dir), self._available())

        try:
            response = LLMResponse.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError as err:
            raise InferenceProtocolError(f"fixture {path} is not a valid response: {err}") from err

        self._consumed.append(
            FixtureUse(key=key, path=path, model_id=response.model_id, attempt=attempt)
        )
        return response

    def _available(self) -> tuple[str, ...]:
        if not self._fixture_dir.is_dir():
            return ()
        return tuple(
            sorted(
                path.stem
                for path in self._fixture_dir.glob("*.json")
                if path.name != MODELS_FIXTURE
            )
        )

    def record(self, key: str, response: LLMResponse) -> Path:
        """Write a fixture. Used when capturing a real session for replay.

        Kept here rather than in a script so that the recording format and the
        replay format cannot drift apart.
        """
        self._fixture_dir.mkdir(parents=True, exist_ok=True)
        path = self._fixture_dir / f"{key}.json"
        path.write_text(response.model_dump_json(), encoding="utf-8")
        return path


class RecordingProvider:
    """Passes calls through to a real provider and writes each exchange as a fixture.

    A flag on `map run` rather than a separate capture script, because a fixture
    that came from a different code path is not a fixture — it is a guess about
    what the real path would have produced. Recording here means the key, the
    prompt and the response are exactly the ones production used.

    The destination is always explicit (`--record-to <dir>`) and has no default:
    a production command must never write into `tests/fixtures/` on its own.
    Copying a recording into the test corpus stays a deliberate human act, and it
    matters because **recordings contain news text**, which is third-party content
    that may not be redistributable.
    """

    def __init__(self, inner: LLMProvider, destination: Path) -> None:
        self._inner = inner
        self._writer = FakeProvider(destination)
        self._destination = destination
        self._recorded: list[Path] = []

    @property
    def recorded(self) -> tuple[Path, ...]:
        return tuple(self._recorded)

    def list_models(self) -> Sequence[ModelInfo]:
        models = self._inner.list_models()
        self._destination.mkdir(parents=True, exist_ok=True)
        (self._destination / MODELS_FIXTURE).write_text(
            json.dumps([model.model_dump() for model in models], indent=2), encoding="utf-8"
        )
        return models

    def complete(
        self,
        *,
        model: ModelInfo,
        prompt: RenderedPrompt,
        sampling: SamplingParams,
        json_schema: Mapping[str, Any] | None = None,
        attempt: int = 0,
    ) -> LLMResponse:
        response = self._inner.complete(
            model=model,
            prompt=prompt,
            sampling=sampling,
            json_schema=json_schema,
            attempt=attempt,
        )
        key = request_key(
            model=model,
            prompt=prompt,
            sampling=sampling,
            json_schema=json_schema,
            attempt=attempt,
        )
        self._recorded.append(self._writer.record(key, response))
        return response
