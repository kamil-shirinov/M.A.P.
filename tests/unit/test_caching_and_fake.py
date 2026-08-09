"""The cache decorator and the fixture-replaying provider.

The cache test that matters most is the one asserting **zero** calls reach the
inner provider on a hit — that is DoD criterion 5 reduced to something a test can
check without a stopwatch or a running model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from mapf.core.errors import FixtureNotFoundError, InferenceProtocolError
from mapf.core.ports import (
    LLMResponse,
    Message,
    ModelInfo,
    RenderedPrompt,
    SamplingParams,
)
from mapf.providers.caching import CachingProvider
from mapf.providers.fake import FakeProvider
from mapf.providers.keys import request_key

PROMPT = RenderedPrompt(
    template_name="structuralist",
    template_version="v1",
    template_sha256="0" * 64,
    messages=(Message(role="user", content="produce scenarios"),),
)
OTHER_PROMPT = RenderedPrompt(
    template_name="structuralist",
    template_version="v1",
    template_sha256="0" * 64,
    messages=(Message(role="user", content="produce different scenarios"),),
)
SAMPLING = SamplingParams(temperature=0.0, seed=7)
MODEL = ModelInfo(id="qwen3-4b", fingerprint="fp-a", fingerprint_source="digest")
OTHER_MODEL = ModelInfo(id="qwen3-4b", fingerprint="fp-b", fingerprint_source="digest")


class CountingProvider:
    """Counts how many times the wrapped provider was actually reached."""

    def __init__(self, text: str = '{"ok": true}') -> None:
        self.calls = 0
        self.list_calls = 0
        self._text = text

    def list_models(self) -> Sequence[ModelInfo]:
        self.list_calls += 1
        return (MODEL,)

    def complete(
        self,
        *,
        model: ModelInfo,
        prompt: RenderedPrompt,
        sampling: SamplingParams,
        json_schema: Mapping[str, Any] | None = None,
        attempt: int = 0,
    ) -> LLMResponse:
        self.calls += 1
        return LLMResponse(text=self._text, model_id=model.id, completion_tokens=self.calls)


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------
def test_a_hit_reaches_the_inner_provider_zero_times(tmp_path: Path) -> None:
    """DoD criterion 5, stated as an assertion rather than a wall-clock measurement."""
    inner = CountingProvider()
    cache = CachingProvider(inner, tmp_path)

    first = cache.complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)
    assert inner.calls == 1
    assert first.cache_hit is False

    second = cache.complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)
    assert inner.calls == 1
    assert second.cache_hit is True
    assert second.text == first.text


def test_a_hit_survives_a_new_provider_instance(tmp_path: Path) -> None:
    """The cache is on disk, so it must outlive the process that filled it —
    otherwise a second `map run` is not a hit at all."""
    CachingProvider(CountingProvider(), tmp_path).complete(
        model=MODEL, prompt=PROMPT, sampling=SAMPLING
    )
    inner = CountingProvider()
    response = CachingProvider(inner, tmp_path).complete(
        model=MODEL, prompt=PROMPT, sampling=SAMPLING
    )
    assert inner.calls == 0
    assert response.cache_hit is True


def test_discovery_is_never_cached(tmp_path: Path) -> None:
    """Caching `list_models` would hide exactly the change the fingerprint exists
    to catch."""
    inner = CountingProvider()
    cache = CachingProvider(inner, tmp_path)
    cache.list_models()
    cache.list_models()
    assert inner.list_calls == 2


@pytest.mark.parametrize(
    ("label", "kwargs"),
    [
        ("prompt", {"prompt": OTHER_PROMPT}),
        ("fingerprint", {"model": OTHER_MODEL}),
        ("sampling", {"sampling": SamplingParams(temperature=0.0, seed=8)}),
        ("attempt", {"attempt": 1}),
        ("schema", {"json_schema": {"type": "object"}}),
    ],
)
def test_every_component_of_the_key_forces_a_miss(
    tmp_path: Path, label: str, kwargs: dict[str, Any]
) -> None:
    """Each of these changes the response the model would produce, so serving a hit
    across them would be a false hit — the expensive direction (ADR 0001)."""
    inner = CountingProvider()
    cache = CachingProvider(inner, tmp_path)
    base: dict[str, Any] = {"model": MODEL, "prompt": PROMPT, "sampling": SAMPLING}
    cache.complete(**base)
    cache.complete(**{**base, **kwargs})
    assert inner.calls == 2, f"{label} did not change the cache key"


def test_different_fingerprints_use_different_namespaces(tmp_path: Path) -> None:
    cache = CachingProvider(CountingProvider(), tmp_path)
    cache.complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)
    cache.complete(model=OTHER_MODEL, prompt=PROMPT, sampling=SAMPLING)
    assert {path.name for path in tmp_path.iterdir()} == {"fp-a", "fp-b"}


def test_a_corrupt_entry_is_a_miss_not_a_crash(tmp_path: Path) -> None:
    """Half-written files are what a SIGKILL mid-write leaves behind. Losing a run
    to one would be worse than recomputing it."""
    inner = CountingProvider()
    cache = CachingProvider(inner, tmp_path)
    cache.complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)

    entry = next(tmp_path.rglob("*.json"))
    entry.write_text("{ truncated", encoding="utf-8")

    with capture_logs() as logs:
        response = cache.complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)
    assert inner.calls == 2
    assert response.cache_hit is False
    assert any(entry["event"] == "cache_entry_unreadable" for entry in logs)


def test_writes_leave_no_partial_files(tmp_path: Path) -> None:
    CachingProvider(CountingProvider(), tmp_path).complete(
        model=MODEL, prompt=PROMPT, sampling=SAMPLING
    )
    assert list(tmp_path.rglob("*.tmp")) == []


# ---------------------------------------------------------------------------
# FakeProvider
# ---------------------------------------------------------------------------
def test_fixtures_replay_by_the_same_key_the_cache_uses(tmp_path: Path) -> None:
    """A fixture recorded under one derivation and read under another is a silent,
    permanent miss — so both use `request_key`."""
    fake = FakeProvider(tmp_path)
    key = request_key(model=MODEL, prompt=PROMPT, sampling=SAMPLING)
    fake.record(key, LLMResponse(text='{"replayed": true}', model_id="qwen3-4b"))

    response = fake.complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)
    assert response.text == '{"replayed": true}'


def test_replay_is_inspectable(tmp_path: Path) -> None:
    """When a test fails, which fixture it consumed must be visible rather than
    guessed at."""
    fake = FakeProvider(tmp_path)
    key = request_key(model=MODEL, prompt=PROMPT, sampling=SAMPLING, attempt=2)
    fake.record(key, LLMResponse(text="{}", model_id="qwen3-4b"))

    fake.complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING, attempt=2)
    (use,) = fake.consumed
    assert use.key == key
    assert use.path.name == f"{key}.json"
    assert use.attempt == 2


def test_replay_is_deterministic(tmp_path: Path) -> None:
    fake = FakeProvider(tmp_path)
    fake.record(
        request_key(model=MODEL, prompt=PROMPT, sampling=SAMPLING),
        LLMResponse(text="stable", model_id="qwen3-4b"),
    )
    first = fake.complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)
    second = fake.complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)
    assert first == second
    assert len(fake.consumed) == 2


def test_the_fixture_directory_is_readable_for_diagnostics(tmp_path: Path) -> None:
    assert FakeProvider(tmp_path).fixture_dir == tmp_path


def test_a_nonexistent_fixture_directory_is_not_a_crash(tmp_path: Path) -> None:
    """The first run before anything is recorded must fail with the actionable
    error, not with an OSError from globbing a directory that is not there."""
    with pytest.raises(FixtureNotFoundError, match=r"\(none\)"):
        FakeProvider(tmp_path / "absent").complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)


def test_a_missing_fixture_names_the_key_and_what_exists(tmp_path: Path) -> None:
    """The usual cause is a prompt or sampling change that silently moved the key."""
    fake = FakeProvider(tmp_path)
    fake.record("deadbeef", LLMResponse(text="{}", model_id="m"))

    with pytest.raises(FixtureNotFoundError) as caught:
        fake.complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)
    assert caught.value.available == ("deadbeef",)
    assert "deadbeef" in str(caught.value)
    assert str(tmp_path) in str(caught.value)


def test_an_empty_fixture_directory_says_so(tmp_path: Path) -> None:
    with pytest.raises(FixtureNotFoundError, match=r"\(none\)"):
        FakeProvider(tmp_path).complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)


def test_injected_models_win_over_the_file(tmp_path: Path) -> None:
    (tmp_path / "models.json").write_text(
        '[{"id": "from-file", "fingerprint": "f", "fingerprint_source": "tag"}]',
        encoding="utf-8",
    )
    fake = FakeProvider(tmp_path, models=(MODEL,))
    assert [info.id for info in fake.list_models()] == ["qwen3-4b"]


def test_models_are_replayed_from_file_when_not_injected(tmp_path: Path) -> None:
    """What lets the CLI run offline: the fixture set stands in for a whole server."""
    (tmp_path / "models.json").write_text(
        '[{"id": "from-file", "fingerprint": "f", "fingerprint_source": "tag"}]',
        encoding="utf-8",
    )
    assert [info.id for info in FakeProvider(tmp_path).list_models()] == ["from-file"]


def test_no_models_fixture_is_an_empty_list_not_an_error(tmp_path: Path) -> None:
    assert FakeProvider(tmp_path).list_models() == ()


def test_a_malformed_models_fixture_is_a_protocol_error(tmp_path: Path) -> None:
    (tmp_path / "models.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(InferenceProtocolError, match="not valid JSON"):
        FakeProvider(tmp_path).list_models()


def test_a_models_fixture_that_is_not_a_list_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "models.json").write_text('{"id": "x"}', encoding="utf-8")
    with pytest.raises(InferenceProtocolError, match="list of models"):
        FakeProvider(tmp_path).list_models()


def test_a_corrupt_response_fixture_is_a_protocol_error(tmp_path: Path) -> None:
    key = request_key(model=MODEL, prompt=PROMPT, sampling=SAMPLING)
    (tmp_path / f"{key}.json").write_text("{ truncated", encoding="utf-8")
    with pytest.raises(InferenceProtocolError, match="not a valid response"):
        FakeProvider(tmp_path).complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)


def test_the_models_fixture_is_not_offered_as_a_response(tmp_path: Path) -> None:
    """`models.json` is discovery data, not a recorded completion."""
    (tmp_path / "models.json").write_text("[]", encoding="utf-8")
    with pytest.raises(FixtureNotFoundError) as caught:
        FakeProvider(tmp_path).complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)
    assert caught.value.available == ()


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------
def test_the_cache_wraps_the_fake_without_either_knowing(tmp_path: Path) -> None:
    """Both satisfy the same Protocol, so bootstrap can stack them in any order —
    which is what keeps the whole pipeline runnable with no server."""
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    fake = FakeProvider(fixtures)
    fake.record(
        request_key(model=MODEL, prompt=PROMPT, sampling=SAMPLING),
        LLMResponse(text="offline", model_id="qwen3-4b"),
    )

    cache = CachingProvider(fake, tmp_path / "cache")
    assert cache.complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING).text == "offline"
    second = cache.complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)
    assert second.cache_hit is True
    assert len(fake.consumed) == 1
