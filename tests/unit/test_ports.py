"""The boundary contracts.

The important assertion in this file is made by **mypy, not pytest**: `_accepts_*`
takes the Protocol type, and passing a stub to it fails type-checking the moment
the stub and the Protocol drift. Running it merely proves the stub is
constructible.

This is also the smallest possible demonstration of DoD criterion 6 — a complete
`LLMProvider` implemented in a test file, with no HTTP client anywhere in its
import graph.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from mapf.core.models import PriceWindow, Symbol, SymbolMatch, TrustedText
from mapf.core.ports import (
    LLMProvider,
    LLMResponse,
    MarketDataProvider,
    Message,
    ModelInfo,
    PromptStore,
    RenderedPrompt,
    SamplingParams,
    SymbolIndex,
    Trace,
    TraceEvent,
)
from mapf.core.quarantine import QuarantinedText

MODEL = ModelInfo(id="qwen3-4b", fingerprint="abc123", fingerprint_source="tag")
PROMPT = RenderedPrompt(
    template_name="structuralist",
    template_version="v1",
    template_sha256="0" * 64,
    messages=(Message(role="user", content="hello"),),
)


# ---------------------------------------------------------------------------
# Stub implementations — structural conformance is checked by mypy
# ---------------------------------------------------------------------------
class StubLLMProvider:
    def list_models(self) -> Sequence[ModelInfo]:
        return [MODEL]

    def complete(
        self,
        *,
        model: ModelInfo,
        prompt: RenderedPrompt,
        sampling: SamplingParams,
        json_schema: Mapping[str, Any] | None = None,
        attempt: int = 0,
    ) -> LLMResponse:
        return LLMResponse(text="{}", model_id=model.id, cache_hit=True)


class StubMarketData:
    @property
    def name(self) -> str:
        return "stub"

    def get_ohlcv(self, ticker: str, start: date, end: date) -> PriceWindow:
        raise NotImplementedError


class StubSymbolIndex:
    def search(self, query: str, *, limit: int = 10) -> Sequence[SymbolMatch]:
        return [SymbolMatch(symbol=Symbol(ticker="AAPL", name="Apple Inc."), score=1.0)]

    def get(self, ticker: str) -> Symbol | None:
        return None


class StubPromptStore:
    def render(
        self,
        name: str,
        version: str,
        *,
        trusted: Mapping[str, TrustedText] | None = None,
        untrusted: Mapping[str, QuarantinedText] | None = None,
    ) -> RenderedPrompt:
        return PROMPT


class StubTrace:
    def __init__(self) -> None:
        self.records: list[tuple[str, int, bool]] = []

    def record(
        self,
        *,
        stage: str,
        attempt: int = 0,
        cache_hit: bool = False,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        self.records.append((stage, attempt, cache_hit))


def _accepts_llm(provider: LLMProvider) -> Sequence[ModelInfo]:
    return provider.list_models()


def _accepts_market_data(provider: MarketDataProvider) -> str:
    return provider.name


def _accepts_symbol_index(index: SymbolIndex) -> Sequence[SymbolMatch]:
    return index.search("apple")


def _accepts_prompt_store(store: PromptStore) -> RenderedPrompt:
    return store.render("structuralist", "v1")


def _accepts_trace(trace: Trace, stage: str) -> None:
    trace.record(stage=stage, attempt=1, cache_hit=True)


def test_stubs_satisfy_their_protocols() -> None:
    assert _accepts_llm(StubLLMProvider()) == [MODEL]
    assert _accepts_market_data(StubMarketData()) == "stub"
    assert _accepts_symbol_index(StubSymbolIndex())[0].symbol.ticker == "AAPL"
    assert _accepts_prompt_store(StubPromptStore()) == PROMPT


def test_trace_records_events() -> None:
    trace = StubTrace()
    _accepts_trace(trace, "intake")
    assert trace.records == [("intake", 1, True)]


# ---------------------------------------------------------------------------
# Boundary vocabulary
# ---------------------------------------------------------------------------
def test_fingerprint_source_is_constrained() -> None:
    """Only the three degradation steps in ADR 0001 are representable."""
    for source in ("digest", "composite", "tag"):
        assert ModelInfo(id="m", fingerprint="f", fingerprint_source=source).fingerprint_source
    with pytest.raises(ValidationError):
        ModelInfo(id="m", fingerprint="f", fingerprint_source="guess")  # type: ignore[arg-type]


def test_composite_fingerprints_can_record_their_field_list() -> None:
    """A composite computed from a different field set is a different fingerprint
    for identical weights, so the fields are part of the record (ADR 0001)."""
    info = ModelInfo(
        id="m",
        fingerprint="f",
        fingerprint_source="composite",
        fingerprint_fields=("created", "size"),
    )
    assert info.fingerprint_fields == ("created", "size")


def test_fingerprint_fields_default_to_empty() -> None:
    assert MODEL.fingerprint_fields == ()


def test_sampling_params_reject_out_of_range_temperature() -> None:
    with pytest.raises(ValidationError):
        SamplingParams(temperature=-0.1)


def test_sampling_params_allow_an_absent_seed() -> None:
    """Recorded as requested; many local backends ignore it entirely."""
    assert SamplingParams(temperature=0.0).seed is None


def test_llm_response_defaults_to_cache_miss() -> None:
    assert LLMResponse(text="x", model_id="m").cache_hit is False


def test_rendered_prompt_requires_a_bare_hex_template_hash() -> None:
    with pytest.raises(ValidationError):
        RenderedPrompt(
            template_name="t",
            template_version="v1",
            template_sha256="sha256:" + "0" * 64,
            messages=(Message(role="user", content="hi"),),
        )


def test_rendered_prompt_requires_at_least_one_message() -> None:
    with pytest.raises(ValidationError):
        RenderedPrompt(
            template_name="t", template_version="v1", template_sha256="0" * 64, messages=()
        )


def test_trace_event_defaults_to_attempt_zero_and_no_cache_hit() -> None:
    event = TraceEvent(at=datetime(2026, 8, 9, tzinfo=UTC), stage="analyst")
    assert (event.attempt, event.cache_hit, dict(event.data)) == (0, False, {})


def test_trace_event_rejects_a_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        TraceEvent(at=datetime(2026, 8, 9), stage="analyst")  # noqa: DTZ001
