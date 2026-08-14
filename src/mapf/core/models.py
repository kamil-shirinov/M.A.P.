"""Domain types.

Why this module holds no I/O and no clock: `core` is the layer every other package
imports (ADR 0004), so anything impure here is impure everywhere. `as_of` and
`run_id` are injected rather than defaulted, which is what makes a run replayable
from its manifest — a model that defaults `as_of` to "now" produces a different
object every time it is constructed and cannot be reconstructed from a trace.

Why prices are `float` and not `Decimal`: this project does statistics, not
accounting. No exact monetary arithmetic occurs, and the Phase 2 Monte Carlo
consumes float64 regardless. `Decimal` would buy precision nobody spends.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from itertools import pairwise
from typing import Annotated, Literal, NewType, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Trust marking (ADR 0005)
# ---------------------------------------------------------------------------
# Two distinct NewTypes over `str`. They are mutually unassignable, and a plain
# `str` satisfies neither without an explicit constructor call, so mypy rejects
# untrusted text reaching a slot the model will read as instructions.
#
# This is a STATIC guarantee. At runtime a NewType is the identity function and
# pydantic validates both as `str`. It protects the codebase under CI; it is not
# a runtime sandbox and must never be described as one.

TrustedText = NewType("TrustedText", str)
"""Text authored by us — prompt templates, field labels, our own instructions."""

UntrustedText = NewType("UntrustedText", str)
"""Text that originated outside the system, or was derived from text that did.

Taint propagates: model output computed from feed text is still untrusted,
because it is interpolated into the next agent's prompt.
"""


# ---------------------------------------------------------------------------
# Shared constrained types
# ---------------------------------------------------------------------------
def _normalise_ticker(value: str) -> str:
    cleaned = value.strip().upper()
    if not cleaned:
        raise ValueError("ticker must not be blank")
    return cleaned


def _require_utc(value: datetime) -> datetime:
    """Reject naive datetimes outright rather than guessing a zone.

    A naive timestamp in a forecast is unscoreable: Phase 2 cannot line it up
    against a market close without knowing which day it belongs to.
    """
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


Ticker = Annotated[str, Field(min_length=1, max_length=16), AfterValidator(_normalise_ticker)]
UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
DocumentId = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]

ADJUSTMENT_BASIS = "split_adjusted"
"""The single canonical price semantic (ADR 0003, amended by ADR 0012).

Split-adjusted only, not dividend-adjusted, for three reasons: it is the basis
both providers can actually produce, so the fallback works at all; it is what
`price_modifier_pct` forecasts, since that is a price move rather than a total
return; and splits are rare where dividends are quarterly, which shrinks the
retroactive-drift surface by an order of magnitude.

A `Literal` on `PriceWindow` rather than a free string, so adding a second basis
is a deliberate, typed change that fails loudly everywhere it matters.
"""


class DomainModel(BaseModel):
    """Frozen and closed by default.

    `extra="forbid"` is not only hygiene: it renders as `additionalProperties:
    false` in the generated JSON Schema, which is what keeps Agent 3's decoding
    grammar tight (ADR 0002).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------
class Symbol(DomainModel):
    ticker: Ticker
    name: str = Field(min_length=1)
    # Absent for non-US pass-through listings, which never enter the SEC index.
    exchange: str | None = None
    cik: int | None = Field(default=None, ge=1)


class SymbolMatch(DomainModel):
    """A ranked search candidate. `map search` never guesses — it returns these."""

    symbol: Symbol
    score: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------
class EarningsFiling(DomainModel):
    """One Item 2.02 8-K, identified well enough to fetch again.

    The accession number is what makes a corpus item reproducible. A ticker and a
    date very nearly resolve to a single filing, but not quite: an 8-K/A amendment
    or two same-day filings are both real, and both would be ambiguous.
    """

    accession: str = Field(pattern=r"^\d{10}-\d{2}-\d{6}$")
    cik: int = Field(ge=1)
    filed: date

    @property
    def path_segment(self) -> str:
        """EDGAR's archive directories strip the dashes from an accession."""
        return self.accession.replace("-", "")


class Document(DomainModel):
    """A unit of untrusted input.

    `text` is raw — never pre-wrapped in delimiters — and `id` hashes the bytes
    exactly as they arrived (ADR 0005). Quarantine happens at render time, so the
    id stays an honest record of the source rather than of our rendering.
    """

    id: DocumentId
    source: str = Field(min_length=1)
    text: UntrustedText = Field(min_length=1)
    fetched_at: UtcDatetime


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------
class Bar(DomainModel):
    date: date
    open: float = Field(gt=0.0)
    high: float = Field(gt=0.0)
    low: float = Field(gt=0.0)
    close: float = Field(gt=0.0)
    volume: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_ohlc_bounds(self) -> Self:
        """Catch provider corruption at the boundary rather than in a ratio."""
        if self.low > self.high:
            raise ValueError(f"low {self.low} exceeds high {self.high}")
        if not (self.low <= self.open <= self.high):
            raise ValueError(f"open {self.open} outside [{self.low}, {self.high}]")
        if not (self.low <= self.close <= self.high):
            raise ValueError(f"close {self.close} outside [{self.low}, {self.high}]")
        return self


class PriceWindow(DomainModel):
    """A contiguous price series with its provenance attached.

    Deliberately not a DataFrame. A bare frame cannot carry `provider` or
    `adjustment`, and ADR 0003 requires both be recorded — two providers with
    different adjustment semantics produce well-formed frames that silently mean
    different things. `mapf.data` converts to pandas for anyone who wants it.
    """

    ticker: Ticker
    provider: str = Field(min_length=1)
    adjustment: Literal["split_adjusted"]
    bars: tuple[Bar, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_strictly_increasing(self) -> Self:
        """Duplicate or out-of-order dates mean a bad merge; refuse to carry it."""
        dates = [bar.date for bar in self.bars]
        for earlier, later in pairwise(dates):
            if later <= earlier:
                raise ValueError(
                    f"bars must be strictly increasing by date: {earlier} then {later}"
                )
        return self

    @property
    def last_trading_date(self) -> date:
        """The date passed to prompts in place of a wall clock (ADR 0001)."""
        return self.bars[-1].date

    @property
    def last_close(self) -> float:
        """The `spot_price` a forecast is scored against."""
        return self.bars[-1].close


class DividendWindow(DomainModel):
    """What was knowable about ex-dividends inside a forecast window (ADR 0013).

    A split-adjusted series keeps the ex-dividend drop, so an ex-date inside the
    window is a mechanical decline the model had no information about. Phase 2
    must be able to exclude or correct those windows.

    `known` is the field that matters. The window is in the future at run time, so
    an ex-date inside it may simply not be announced yet — without this flag,
    `ex_dates: ()` is ambiguous between "no dividend" and "not knowable", and
    reading the second as the first silently treats a contaminated window as clean.
    **An absent flag is never an absence of dividends.**
    """

    start: date
    end: date
    ex_dates: tuple[date, ...] = ()
    total_amount: float = Field(default=0.0, ge=0.0)
    known: bool = False
    source: str = "unknown"

    @model_validator(mode="after")
    def _check_window(self) -> Self:
        if self.end < self.start:
            raise ValueError(f"window ends {self.end} before it starts {self.start}")
        if not self.known and (self.ex_dates or self.total_amount):
            raise ValueError("cannot report ex-dividend detail while known is False")
        return self


# ---------------------------------------------------------------------------
# Agent inputs and outputs
# ---------------------------------------------------------------------------
class MaterialFacts(DomainModel):
    """Agent 1's output. Untrusted: it is derived from feed text and feeds a prompt."""

    ticker: Ticker
    facts: tuple[UntrustedText, ...] = Field(min_length=1)
    source_doc_ids: tuple[DocumentId, ...] = Field(min_length=1)


class ScenarioNarrative(DomainModel):
    """Agent 2's output. Prose, not numbers — Agent 3 does the structuring."""

    ticker: Ticker
    horizon_days: int = Field(ge=1, le=252)
    text: UntrustedText = Field(min_length=1)
    source_doc_ids: tuple[DocumentId, ...] = Field(min_length=1)


class Scenario(DomainModel):
    """One branch of the forecast.

    **Every number here is a decimal fraction.** `price_return` of 0.045 is a 4.5%
    move; `annualised_vol` of 0.22 is 22% annualised. One convention across the
    whole object, deliberately.

    The first live run produced 0.05 / 0.0 / -0.1 from an analyst arguing "moderate
    up / flat / sharp down" — coherent as fractions, meaningless as percentage
    points. The two numeric fields sat adjacent on *different* conventions and the
    field names taught the inconsistency: one carried a `_pct` suffix and the other
    did not. Nothing told the model which was which, because the schema
    descriptions that might have are stripped before it ever sees them (ADR 0002).

    Fractions rather than percentage points because volatility is conventionally a
    decimal in finance, and because Phase 2's Monte Carlo consumes fractions and
    would otherwise divide by 100 at the boundary — a conversion that exists only
    to undo a presentation choice.

    `justification` is declared first on purpose. Pydantic preserves declaration
    order in the generated schema, and a constrained decoder emits fields in schema
    order — so the model states its reasoning before committing to the numbers,
    conditioning them on it rather than rationalising afterwards (ADR 0006).
    """

    # 400. It was cut to 240 after the model pasted the analyst's paragraph and
    # truncated mid-word in all three branches — on the theory that a budget too
    # small to paste into would force compression. That theory was wrong (ADR
    # 0014): at 240 it still pasted and still truncated, just earlier. The model
    # copied because it was *told to transcribe*, and the v2 instruction "the
    # justification is yours, not the analyst's" is what stopped it.
    #
    # So 240 was constraining real synthesis rather than preventing copying — the
    # longest justification of the first clean v2 run came in at 234 of 240.
    # `QualityFlags.justifications_at_ceiling` is the regression signal that makes
    # raising it safe: if copying returns, lengths pile up at the cap and the
    # manifest says so.
    justification: str = Field(min_length=20, max_length=400)
    probability_weight: float = Field(ge=0.0, le=1.0)
    # -1.0 is a total loss; below it is a negative price. The upper rail is a
    # sanity bound, not a market claim.
    price_return: float = Field(gt=-1.0, le=10.0)
    annualised_vol: float = Field(gt=0.0, le=3.0)


class ScenarioSet(DomainModel):
    """The only part of a forecast the model authors (ADR 0002).

    The grammar guarantees shape — types, bounds, string lengths. It cannot
    express either invariant below, because both span fields. That gap is exactly
    what the repair loop answers.
    """

    bullish: Scenario
    base_case: Scenario
    bearish: Scenario

    @model_validator(mode="after")
    def _check_weights_sum_to_one(self) -> Self:
        total = self.bullish.probability_weight + self.base_case.probability_weight
        total += self.bearish.probability_weight
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"probability_weight values must sum to 1.0 (+/-1e-6), got {total!r}")
        return self

    @model_validator(mode="after")
    def _check_returns_ordered(self) -> Self:
        bear = self.bearish.price_return
        base = self.base_case.price_return
        bull = self.bullish.price_return
        if not (bear < base < bull):
            raise ValueError(
                "price_return must be strictly ordered "
                f"bearish < base_case < bullish, got {bear!r} < {base!r} < {bull!r}"
            )
        return self


class ModelVersions(DomainModel):
    """Which weights produced this forecast. Fingerprints, not tags (ADR 0001)."""

    intake: str = Field(min_length=1)
    analyst: str = Field(min_length=1)
    structuralist: str = Field(min_length=1)


class Forecast(DomainModel):
    """The Phase 1 artifact.

    Assembled by `mapf.pipeline` from a `ScenarioSet` plus metadata it already
    holds (ADR 0002). Field order matches the agreed on-disk shape.
    """

    # 2.0.0, not 1.1.0: `price_modifier_pct` became `price_return` and its units
    # changed from percentage points to a fraction. A 1.x reader would parse a 2.0
    # artifact without error and be wrong by a factor of 100. Phase 2 must refuse
    # to score across the boundary (ADR 0012).
    schema_version: Literal["2.0.0"] = "2.0.0"
    run_id: UUID
    ticker: Ticker
    as_of: UtcDatetime
    horizon_days: int = Field(ge=1, le=252)
    spot_price: float = Field(gt=0.0)
    source_doc_ids: tuple[DocumentId, ...] = Field(min_length=1)
    model_versions: ModelVersions
    scenarios: ScenarioSet
