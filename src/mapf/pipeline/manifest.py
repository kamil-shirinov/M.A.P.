"""The run manifest — the Phase 2 handshake.

A typed model rather than a dict, deliberately. This is the artifact a scoring
harness reads months from now, and a dict lets a missing field surface as a
`KeyError` at that point instead of a validation error today. **If Phase 2 would
need it and it is not here, that is a bug now, not later.**

What it must carry, and why each one is load-bearing:

- **model fingerprints and `fingerprint_source`** — a result derived under a
  composite or a bare tag carries less provenance than one under a digest, and
  Phase 2 has to be able to tell them apart (ADR 0001).
- **prompt name, version and content hash** — provenance, kept separate from cache
  invalidation, which the rendered text already handles (ADR 0001).
- **`source_doc_ids`** — the raw bytes each fact came from (ADR 0005).
- **adjustment, provider, `fetched_on`** — the price vintage. Phase 2 must refuse
  to score across mixed values (ADR 0012).
- **`dividends`** — whether an ex-date falls in the forecast window, and crucially
  whether that was knowable at all (ADR 0013).
- **`allow_nondeterministic`** — marks a run that is not reproducible (ADR 0007).
- **sampling parameters including the seed, recorded as *requested*** — many local
  backends ignore both.
"""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field

from mapf.core.fidelity import TranscriptionFidelity
from mapf.core.models import DividendWindow, DocumentId, DomainModel, Ticker, UtcDatetime
from mapf.core.ports import FingerprintSource, SamplingParams
from mapf.core.provenance import CodeVersion
from mapf.core.quality import QualityFlags


class AgentRecord(DomainModel):
    """Everything needed to reproduce one agent's call, or to know you cannot."""

    alias: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    fingerprint: str = Field(min_length=1)
    fingerprint_source: FingerprintSource
    fingerprint_fields: tuple[str, ...] = ()
    sampling: SamplingParams
    template_name: str = Field(min_length=1)
    template_version: str = Field(min_length=1)
    template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Why the model stopped. "stop" is a completed answer; "length" means it was
    # cut off, so whatever this agent handed downstream is a fragment presented as
    # a whole. Recorded per agent because only the agent knows.
    finish_reason: str | None = None
    output_truncated: bool = False

    attempts: int = Field(default=1, ge=1)
    # A reasoning build can spend most of its budget here and emit nothing.
    # Recorded so the distribution over runs is measurable rather than assumed.
    reasoning_tokens: int = Field(default=0, ge=0)
    cache_hits: int = Field(default=0, ge=0)


class PriceProvenance(DomainModel):
    """Which series was used, and which vintage of it (ADR 0012)."""

    provider: str = Field(min_length=1)
    adjustment: str = Field(min_length=1)
    fetched_on: date
    window_start: date
    window_end: date
    last_trading_date: date
    bars: int = Field(ge=1)


class RunManifest(DomainModel):
    # This manifest's own format version. Distinct from, and easily confused with,
    # the forecast's.
    manifest_version: Literal["1.3.0"] = "1.3.0"
    # The version of the artifact this manifest describes. ADR 0012 makes Phase 2
    # refuse to score across a schema boundary — and Phase 2 reads the *manifest*
    # to decide. With only `schema_version` here it read the manifest's own version
    # and never saw that the forecast had moved to 2.0.0: exactly the silent,
    # plausible mismatch that ADR the whole obligation exists to prevent.
    forecast_schema_version: str = Field(min_length=1)
    run_id: UUID
    ticker: Ticker
    as_of: UtcDatetime
    horizon_days: int = Field(ge=1, le=252)
    spot_price: float = Field(gt=0.0)

    source_doc_ids: tuple[DocumentId, ...] = Field(min_length=1)
    agents: tuple[AgentRecord, ...] = Field(min_length=1)
    prices: PriceProvenance
    dividends: DividendWindow
    # Warnings, never rejections. Phase 2 filters on these rather than
    # rediscovering them one forecast at a time.
    quality: QualityFlags = QualityFlags()
    # v2's premise — analyst states magnitudes, structuralist transcribes — as a
    # number rather than a claim. Two failure modes kept apart because they
    # blame different agents.
    fidelity: TranscriptionFidelity = TranscriptionFidelity()

    # Which code produced this run. A twelve-night corpus that dies and resumes
    # executes its second half under whatever commit is checked out then, and a
    # corpus spanning two commits must be visible rather than invisible.
    code_version: CodeVersion = CodeVersion()

    # Marks a run that is not reproducible. Phase 2 must either exclude these or
    # report them separately (ADR 0007).
    allow_nondeterministic: bool = False

    package_version: str = Field(min_length=1)
    python_version: str = Field(min_length=1)
