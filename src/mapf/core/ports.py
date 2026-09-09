"""Boundary contracts.

Every Protocol here is what an *agent* or the *pipeline* is allowed to depend on.
The concrete implementations live in `mapf.providers` and `mapf.data`, and
`import-linter` forbids either being imported from above (ADR 0004). That is what
makes the test suite runnable with the inference server switched off: an agent
constructed with a fake cannot reach `httpx`, even transitively, so there is
nothing to patch.

None of these Protocols is `runtime_checkable`. The decorator only verifies that
attribute *names* exist — it cannot check signatures — so an `isinstance` pass
against it is close to worthless as a guarantee while reading like a real one.
Add it to a Protocol at the point where something actually needs to branch on
capability at runtime, and not before.

The small data types below exist to give these Protocols signatures. They are the
vocabulary of the boundary, which is why they live here and not in `models` —
`models` is the domain, `ports` is the contract.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Literal, Protocol

from pydantic import Field

from mapf.core.models import (
    DividendWindow,
    DomainModel,
    EarningsFiling,
    PriceWindow,
    Symbol,
    SymbolMatch,
    TrustedText,
    UtcDatetime,
)
from mapf.core.quarantine import QuarantinedText

# ---------------------------------------------------------------------------
# Inference vocabulary
# ---------------------------------------------------------------------------
FingerprintSource = Literal["digest", "composite", "tag"]


class ModelInfo(DomainModel):
    """A model as the server reports it, plus how confidently we can pin it.

    `fingerprint_fields` is not decoration: a composite fingerprint computed from
    a different field set is a different fingerprint for identical weights, so the
    field list is what makes a composite reproducible rather than merely plausible
    (ADR 0001).
    """

    id: str = Field(min_length=1)
    fingerprint: str = Field(min_length=1)
    fingerprint_source: FingerprintSource
    fingerprint_fields: tuple[str, ...] = ()


class Message(DomainModel):
    role: Literal["system", "user", "assistant"]
    content: str


class SamplingParams(DomainModel):
    """Recorded in every manifest as *requested*.

    Local backends frequently ignore `seed`, and some do not implement
    `temperature=0` deterministically. Recording the request is honest;
    claiming reproducibility from it would not be.
    """

    temperature: float = Field(ge=0.0, le=2.0)
    seed: int | None = None
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=1)
    # Sent only on a degeneration retry (ADR 0021), never on a first attempt, so
    # an ordinary call carries no penalty at all. It sits in `SamplingParams`
    # rather than beside it because the cache key hashes this model: a response
    # produced under a penalty must not be served to a request without one.
    frequency_penalty: float | None = Field(default=None, ge=0.0, le=2.0)


class LLMResponse(DomainModel):
    text: str
    model_id: str = Field(min_length=1)
    finish_reason: str | None = None
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    # A reasoning model can burn its whole budget here and emit no answer.
    # Invisible unless recorded, and it looks exactly like a refusal.
    reasoning_tokens: int | None = Field(default=None, ge=0)
    # The reasoning ITSELF, not only its length. The trace claims to hold "every
    # prompt and every raw response", and for a reasoning model most of the raw
    # response was being discarded — so a runaway could be counted and never read
    # (ADR 0027).
    reasoning_text: str | None = None
    # Must be recorded even on a hit, or the second run's trace is empty and
    # DoD criterion 5 becomes unauditable.
    cache_hit: bool = False


class RenderedPrompt(DomainModel):
    """A prompt with its template provenance attached.

    The template hash goes in the manifest, not in the cache key — the rendered
    text is already in the key, so a template edit invalidates on its own.
    Provenance and invalidation are different jobs (ADR 0001).
    """

    template_name: str = Field(min_length=1)
    template_version: str = Field(min_length=1)
    template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    messages: tuple[Message, ...] = Field(min_length=1)


class TraceEvent(DomainModel):
    """One line of `runs/<run_id>/trace.jsonl`."""

    at: UtcDatetime
    stage: str = Field(min_length=1)
    attempt: int = Field(default=0, ge=0)
    cache_hit: bool = False
    data: Mapping[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------
class LLMProvider(Protocol):
    """The only way to reach a model. `mapf.providers` implements it."""

    def list_models(self) -> Sequence[ModelInfo]:
        """Resolve what the server actually has loaded.

        Model ids are never hardcoded: identical weights are named differently by
        different backends, so the id on the wire is whatever this returns.
        """
        ...

    def complete(
        self,
        *,
        model: ModelInfo,
        prompt: RenderedPrompt,
        sampling: SamplingParams,
        json_schema: Mapping[str, Any] | None = None,
        attempt: int = 0,
    ) -> LLMResponse:
        """Run one completion.

        `attempt` exists only to namespace the cache. A repair retry appends the
        validation errors to the prompt, so attempt 2 differs from attempt 1 —
        but when the same errors recur, attempt 3 would render byte-identical to
        attempt 2, hit the cache, and replay a known failure without calling the
        model (ADR 0001).
        """
        ...


class MarketDataProvider(Protocol):
    """One source of prices. Composed into a failover chain by `mapf.data`."""

    @property
    def name(self) -> str:
        """Recorded in the manifest. A run must say which source served it."""
        ...

    def get_ohlcv(self, ticker: str, start: date, end: date) -> PriceWindow:
        """Return a window normalised to the canonical adjustment basis.

        Never returns an empty window: an empty result is
        `EmptyPriceWindowError`, because a silently empty frame propagates as a
        plausible-looking zero-length series (ADR 0003).
        """
        ...


class PriceSnapshotIndex(Protocol):
    """A read-only lookup over one stored price vintage.

    Separate from `MarketDataProvider` because it answers a different question and
    must be unable to answer that one. A provider fetches; this only reads what a
    named snapshot already holds, and says so when it holds nothing. That is what
    makes a number taken through it reproducible: the vintage names the series, and
    no path here can silently substitute today's.
    """

    @property
    def vintage(self) -> date:
        """Which snapshot this reads. Reported with every value taken from it."""
        ...

    def covering(self, ticker: str, start: date, end: date) -> PriceWindow | None:
        """A stored window spanning `start`..`end`, or `None` if none does.

        `None` is an answer, not a failure and never a reason to fetch: the caller
        reports "this vintage does not hold that range" for that item and moves on.
        """
        ...


class DividendSource(Protocol):
    """Ex-dividend dates inside a forecast window (ADR 0013).

    Allowed to fail. A dividend calendar that cannot answer returns
    `known=False`; a forecast is never blocked by it.
    """

    def dividends_in(self, ticker: str, start: date, end: date) -> DividendWindow: ...


class FilingSource(Protocol):
    """Item 2.02 filing dates — quarterly earnings, and nothing else.

    The item filter is the whole point. An 8-K count across *all* item types runs
    8–12 a year and suggests a panel that cannot actually be built; Item 2.02 is
    four a year at most (ADR 0018). Widening it silently changes what a forecast
    window contains.
    """

    def earnings_dates(self, ticker: str, start: date, end: date) -> tuple[date, ...]:
        """Distinct filing dates, ascending. Empty is a legitimate answer."""
        ...

    def earnings_filings(self, ticker: str, start: date, end: date) -> tuple[EarningsFiling, ...]:
        """The same filings with their accession numbers.

        Dates alone identify a forecast window; accessions identify the document.
        Both are needed, and they are not interchangeable: an 8-K/A amendment or
        two same-day filings collapse in the date view and stay distinct here.
        """
        ...


class ExhibitCheck(Protocol):
    """Whether a filing carries a usable Exhibit 99.1.

    A selection criterion, not a runtime condition. Whether a company attaches its
    earnings release as EX-99.1 is a deterministic property of how that company
    files — identical in every band and every quarter — so a filer that does not is
    unusable from the start rather than intermittently unlucky (ADR 0018).
    """

    def has_exhibit(self, filing: EarningsFiling) -> bool: ...


class LiquidityScreen(Protocol):
    """Median daily dollar volume over a window, or `None` for no usable history.

    Kept separate from `MarketDataProvider` because selection asks one summary
    question about a few hundred tickers and must not assemble a full validated
    `PriceWindow` for each only to discard it.

    One number rather than a `has_history` predicate plus a volume lookup: both
    answers come from the same fetch, and splitting them invites two fetches or a
    cache that has to be reasoned about.
    """

    def median_dollar_volume(self, ticker: str, start: date, end: date) -> float | None: ...


class SymbolIndex(Protocol):
    """The local, searchable symbol universe. US-listed only, by construction."""

    def search(self, query: str, *, limit: int = 10) -> Sequence[SymbolMatch]:
        """Ranked candidates. Ambiguity is returned, never resolved silently."""
        ...

    def get(self, ticker: str) -> Symbol | None: ...


class PromptStore(Protocol):
    """Loads versioned templates and renders them with quarantine applied."""

    def render(
        self,
        name: str,
        version: str,
        *,
        trusted: Mapping[str, TrustedText] | None = None,
        untrusted: Mapping[str, QuarantinedText] | None = None,
    ) -> RenderedPrompt:
        """Interpolate slots, delimiting only the untrusted map.

        The two maps are separately typed so that mypy, not reviewer attention, is
        what stops feed text reaching an instruction slot. The untrusted map holds
        `QuarantinedText`, whose only constructor is the sanitiser — so raw feed
        text cannot reach a prompt even through a renderer written later
        (ADR 0005).
        """
        ...


class Trace(Protocol):
    """The audit trail, and the input to the Phase 2 evaluation harness.

    Takes the fields rather than a built `TraceEvent` so that the implementation
    owns the timestamp. Callers therefore need no clock, which keeps the layers
    above free of the one dependency most likely to leak into a prompt and destroy
    the cache (ADR 0001).
    """

    def record(
        self,
        *,
        stage: str,
        attempt: int = 0,
        cache_hit: bool = False,
        data: Mapping[str, Any] | None = None,
    ) -> None: ...
