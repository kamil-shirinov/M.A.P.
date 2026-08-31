"""Execution of the frozen corpus (ADR 0019).

Three properties this module exists to hold, none of which is a default:

**It refuses to start against drifted prompts.** A re-versioned template
invalidates every cache key, turning a 35-second replay into a 500-second
generation, 727 times over. The risk will not present itself as a risk — it
presents itself as a small sensible improvement to a prompt at 1am — so the check
is an assertion at startup, not a warning in a log.

**It halts rather than completing a degraded corpus.** A corpus missing items is
no longer the corpus that was frozen and committed, and the pre-registration claim
weakens without anyone deciding that it should.

**It reports health, never scores.** Fidelity, numeral warnings and failure counts
say whether the machine is working and may be watched during the run. CRPS and
everything derived from it stay behind the scoring command, so nothing the runner
prints can inform the two-pass continuation decision.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from http import HTTPStatus
from math import ceil
from pathlib import Path
from typing import Protocol
from uuid import UUID

import structlog

from mapf.core.errors import (
    ExhibitError,
    ExhibitUnreachableError,
    ForecastRepairExhausted,
    InferenceStatusError,
    InferenceTimeoutError,
    InferenceUnreachableError,
    MapError,
    MarketDataError,
    MissingArtifactError,
    MissingExhibitError,
    ModelBudgetExhaustedError,
    NoMaterialFactsError,
    OutputTruncatedError,
    PromptTooLargeError,
)
from mapf.core.hashing import new_run_id
from mapf.core.models import Document
from mapf.core.ports import DividendSource, MarketDataProvider
from mapf.corpus.ledger import FailureReason, Ledger, LedgerEntry
from mapf.corpus.selection import Corpus
from mapf.pipeline.run import TRACE_FILE, Agents, RunRequest, execute
from mapf.pipeline.trace import CountingTrace, audit_trace

_logger = structlog.get_logger(__name__)


class FreezeMismatchError(MapError):
    """A live template, model or parameter differs from the frozen corpus.

    Refuses rather than warns: the whole point is that this must not be
    discoverable only in hindsight, after the cache has been invalidated.
    """


class CorpusHaltedError(MapError):
    """A failure threshold was crossed. The corpus is incomplete by decision."""

    def __init__(self, trigger: str, counts: Mapping[str, int]) -> None:
        self.trigger = trigger
        self.counts = dict(counts)
        detail = ", ".join(f"{k}={v}" for k, v in sorted(self.counts.items())) or "none"
        super().__init__(f"halted on {trigger}; failures by reason: {detail}")


# ADR 0019 §6. Two triggers, because scattered bad luck and systematic failure do
# not look alike and must not be answered alike.
MAX_CONSECUTIVE_FAILURES = 5
MAX_BAND_FAILURE_RATE = 0.02


# Set by the document callback when the truncation rule bites, so the runner can
# record it without knowing how documents are built.
TRUNCATION_NOTES: dict[tuple[str, str, date], int] = {}


class Wiring(Protocol):
    """One item's agents and its own trace.

    Structural rather than imported: `bootstrap` builds the concrete object, and
    `import-linter` forbids this layer from reaching up to it (ADR 0004).
    """

    agents: Agents
    market: MarketDataProvider
    dividends: DividendSource
    trace: CountingTrace


@dataclass(frozen=True)
class CorpusItem:
    ticker: str
    band: str
    filing_date: date

    @property
    def key(self) -> tuple[str, str, date]:
        return (self.ticker, self.band, self.filing_date)


@dataclass
class Health:
    """Engineering signal, not result (ADR 0019 §7)."""

    completed: int = 0
    failed: int = 0
    unparseable: int = 0
    divergent: int = 0
    ungrounded_numerals: int = 0
    degenerate_spread: int = 0
    budget_exhausted: int = 0
    output_truncated: int = 0
    degeneration_retry: int = 0
    reasoning_tokens: int = 0
    cache_hits: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)

    @property
    def fidelity_ok(self) -> bool:
        """1.0 fidelity is what licenses the structuralist's role (ADR 0017)."""
        return self.unparseable == 0 and self.divergent == 0


def plan(corpus: Corpus, band: str) -> tuple[CorpusItem, ...]:
    """Every item in one band, in a deterministic order."""
    items = [
        CorpusItem(ticker=p.ticker, band=b.band, filing_date=d)
        for p in corpus.accepted
        for b in p.filings
        if b.band == band
        for d in b.dates
    ]
    return tuple(sorted(items, key=lambda i: (i.filing_date, i.ticker)))


# The seed for the execution order (ADR 0028). Recorded in the frozen corpus rather
# than derived, so the order is reproducible from the record alone.
EXECUTION_SEED = 20260830


def execution_order(
    items: Sequence[CorpusItem], done: set[tuple[str, str, date]], *, seed: int
) -> tuple[CorpusItem, ...]:
    """The order to ATTEMPT items in — which is not the order they are planned in.

    **This cannot change what any item produces.** `as_of` comes from the filing
    date, the price vintage is pinned, sampling carries a fixed seed, and the cache
    is keyed on content. Execution order determines one thing only: *which subset
    survives a halt*.

    And that turned out to matter. `plan()` orders by `(filing_date, ticker)`, so a
    halt took a **prefix of the year** rather than a sample of it — losing May
    through August entirely at item 208. That is precisely the confound `passes.py`
    was written to prevent, and its rationale was in writing before any of this:
    a calendar-contiguous subsample "would confound *we stopped early* with *we only
    measured the first half of the year*". The protection existed and had been
    applied to the other band.

    A seeded shuffle rather than a stride, because it makes **any prefix an unbiased
    random sample of the remainder** — a claim that can be stated in a result. A
    stride gives a systematic sample, which is defensible but needs an argument that
    a random one does not.

    The whole band is shuffled and then filtered, not the remainder shuffled: that
    makes the order a function of the corpus and the seed alone, so it is stable
    across resumes rather than reshuffling on each one.

    `plan()` is deliberately untouched. It defines pass membership, which is
    pre-registered (ADR 0019) and computed at scoring time from the planned order —
    so the two are independent and this changes neither.
    """
    ordered = list(items)
    random.Random(seed).shuffle(ordered)
    return tuple(item for item in ordered if item.key not in done)


def verify_freeze(
    frozen: Mapping[str, object],
    *,
    live_digest: Callable[[str, str], str],
    live_models: Mapping[str, Mapping[str, object]],
) -> None:
    """Check live templates and models against the frozen record, or refuse.

    `live_digest(name, version)` hashes the template as it exists now.

    **Every field the freeze records is compared, not just the alias.** Comparing
    only the alias is how `intake.max_tokens` came to sit at `null` in the frozen
    record while the run was configured for 2,048: the freeze held a number, the
    config held a different one, and nothing ever put them side by side. That is
    the same defect as trusting a configured context window instead of probing the
    server (ADR 0020 §4), one layer up.

    Fields absent from the frozen record are not checked — an older freeze is
    allowed to say less, but never to disagree.
    """
    prompts = frozen.get("prompts")
    if not isinstance(prompts, Mapping) or not prompts:
        raise FreezeMismatchError("frozen corpus records no prompt hashes")

    mismatches: list[str] = []
    for agent, spec in prompts.items():
        if not isinstance(spec, Mapping):
            raise FreezeMismatchError(f"malformed frozen prompt entry for {agent!r}")
        template = str(spec["template"])
        name, version = template[: -len(".md")].rsplit(".", 1)
        try:
            actual = live_digest(name, version)
        except MapError as err:
            mismatches.append(f"{agent}: {template} could not be loaded ({err})")
            continue
        if actual != spec["sha256"]:
            mismatches.append(
                f"{agent}: {template} content changed "
                f"(frozen {str(spec['sha256'])[:12]}…, live {actual[:12]}…)"
            )

    models = frozen.get("models")
    if isinstance(models, Mapping):
        for agent, spec in models.items():
            if not isinstance(spec, Mapping):
                continue
            live = live_models.get(agent)
            if live is None:
                continue
            for field, frozen_value in spec.items():
                if field not in live:
                    continue
                if live[field] != frozen_value:
                    mismatches.append(
                        f"{agent}: {field} is {live[field]!r}, frozen as {frozen_value!r}"
                    )

    # The execution seed is a top-level field rather than a per-agent one, and it is
    # checked here for the same reason every other frozen value is: the record holds
    # a number, the code holds a number, and nothing else puts them side by side
    # (finding #26). It changes no forecast — only which subset survives a halt —
    # which is exactly the kind of value that drifts unnoticed.
    order = frozen.get("execution_order")
    if isinstance(order, Mapping) and "seed" in order and order["seed"] != EXECUTION_SEED:
        mismatches.append(
            f"execution seed is {EXECUTION_SEED}, frozen as {order['seed']!r}; "
            "a resume would attempt items in a different order from the record"
        )

    if mismatches:
        raise FreezeMismatchError(
            "live configuration differs from the frozen corpus — every cache key is "
            "invalidated and the run would cost the full budget again:\n  "
            + "\n  ".join(mismatches)
        )


# A REFINEMENT ONLY. Both branches below are terminal, so nothing about resume
# behaviour depends on this matching — it only chooses the more specific of two
# names for the same outcome. That is the shape ADR 0020 §4 settled on for the
# context probe: a parsed message may sharpen a report, never decide one.
_CONTEXT_MARKERS = ("context size", "context length", "context window", "exceeds the available")


# What a completed item must have left behind. Checked rather than assumed: the
# ledger's "append only after every artifact lands" was enforced by ordering alone,
# and ordering does not verify that a write happened.
REQUIRED_ARTIFACTS = ("forecast.json", "manifest.json", TRACE_FILE)


def _verify_artifacts(run_dir: Path, run_id: str) -> None:
    """Every required artifact exists, is non-empty, and — for the trace — is *this
    run's*.

    Empty counts as missing: a zero-byte `trace.jsonl` satisfies an existence check
    and contains no audit trail. So does a trace holding somebody else's events,
    which is why the trace gets an event-count bound rather than only a size check
    (ADR 0022).
    """
    missing = [
        name
        for name in REQUIRED_ARTIFACTS
        if not (path := run_dir / name).is_file() or path.stat().st_size == 0
    ]
    if missing:
        raise MissingArtifactError(run_id, missing)
    if (reason := audit_trace(run_dir / TRACE_FILE)) is not None:
        raise MissingArtifactError(run_id, [f"{TRACE_FILE} ({reason})"])


def _reason_for(error: MapError) -> FailureReason:
    if isinstance(error, MissingArtifactError):
        return "missing_artifact"
    if isinstance(error, OutputTruncatedError):
        # Deterministic at temperature 0: the same document runs away identically
        # on every attempt, so retrying only consumes the failure allowance.
        return "output_truncated"
    if isinstance(error, PromptTooLargeError):
        # Deterministic: the same document produces the same oversized prompt on
        # every attempt, so retrying only consumes the failure allowance.
        return "context_overflow"
    if isinstance(error, InferenceStatusError):
        return _classify_status(error)
    if isinstance(error, MissingExhibitError):
        return "missing_exhibit"
    if isinstance(error, ExhibitUnreachableError):
        # EDGAR was never reached. A property of the afternoon, not of the filing —
        # five items failed together when DNS dropped — so it is excluded from the
        # repeat rule for the same reason `inference_unreachable` is (ADR 0024).
        return "exhibit_unreachable"
    if isinstance(error, ExhibitError):
        # EDGAR answered and refused. That is its view of this filing, and it is the
        # same view next pass, so a repeat here IS evidence about the item.
        return "exhibit_error"
    if isinstance(error, InferenceUnreachableError):
        return "inference_unreachable"
    if isinstance(error, InferenceTimeoutError):
        return "inference_timeout"
    if isinstance(error, ModelBudgetExhaustedError):
        return "budget_exhausted"
    if isinstance(error, MarketDataError):
        return "market_data"
    if isinstance(error, ForecastRepairExhausted):
        return "repair_exhausted"
    if isinstance(error, NoMaterialFactsError):
        return "no_material_facts"
    return "other"


def _classify_status(error: InferenceStatusError) -> FailureReason:
    """Split HTTP status into transient and terminal, **by status code**.

    The exception type alone is too coarse: `InferenceStatusError` covers a 500
    from a server under load, which a retry may well survive, and a 400 rejecting a
    prompt longer than the context, which will fail identically forever. Retrying
    the latter consumes the failure allowance each pass until the run halts on
    items that can never succeed — the first corpus run recorded eight of them as
    transient `other`.

    **The split is the status class, not the wording.** This matched four English
    phrases in the body, so a server phrasing its refusal differently fell through
    to `other` — transient — and reintroduced exactly that failure. It was also the
    vendor coupling `CLAUDE.md` §3 forbids, and the one ADR 0020 §4 had already
    removed from the context probe for the same reason; leaving it here meant the
    lesson was applied in one place and not the other (ADR 0022).

    A 4xx means *this request* is unacceptable and an identical retry will be
    refused identically. A 5xx means the server is unwell, which a retry may
    survive. The naming of the *cause* is where a parsed message may still help, so
    it is kept as a refinement — never as the thing that decides transient from
    terminal. The cost of the stricter rule: a misconfigured server 400s every
    item, and up to five go terminal before the consecutive-failure halt fires.
    Those five need their ledger lines removed by hand — a bounded, visible price
    for not retrying the unretryable forever.
    """
    if error.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        return "other"
    if error.status_code >= HTTPStatus.BAD_REQUEST:
        body = error.body.lower()
        if any(m in body for m in _CONTEXT_MARKERS):
            return "context_overflow"
        return "request_rejected"
    return "other"


@dataclass(frozen=True)
class RunnerConfig:
    runs_dir: Path
    price_vintage: date
    # Fixed here rather than passed per call, so a run cannot quietly execute in a
    # different order from the one the freeze records (ADR 0028).
    execution_seed: int = EXECUTION_SEED
    # Stamped into every manifest so a band spanning two frozen records is
    # detectable at scoring time (ADR 0022). Optional only so a caller outside a
    # corpus need not invent one.
    freeze_version: str | None = None
    # What is compared at scoring time. Two of them, because the truncation rule
    # governs only the items it actually applied to: an untruncated exhibit was asked
    # the same question whatever the rule says (ADR 0029, amended).
    freeze_digest: str | None = None
    freeze_digest_truncated: str | None = None
    history_days: int = 730
    horizon_days: int = 5
    attempts: int = 3
    backoff_s: float = 30.0
    max_consecutive_failures: int = MAX_CONSECUTIVE_FAILURES
    max_band_failure_rate: float = MAX_BAND_FAILURE_RATE
    # Never rendered here, and asserted rather than defaulted (ADR 0019 §5).
    render_chart: bool = False


def run_band(
    items: Sequence[CorpusItem],
    *,
    documents: Callable[[CorpusItem], tuple[Document, ...]],
    wiring: Callable[[UUID], Wiring],
    ledger: Ledger,
    config: RunnerConfig,
    sleep: Callable[[float], None] = time.sleep,
    on_progress: Callable[[int, int, CorpusItem, LedgerEntry, Health], None] | None = None,
) -> Health:
    """Execute one band, resuming from the ledger and halting on threshold.

    Raises `CorpusHaltedError` when a threshold is crossed. Everything completed
    up to that point is already durable — the ledger is appended per item — so a
    halt costs the diagnosis, never the work.

    `wiring` is a **factory**, called once per item with that item's run id. It has
    to be: `CountingTrace` accumulates per stage, and one instance shared across a
    band reports band-cumulative attempts, cache hits and reasoning tokens in every
    manifest, while every item after the first truncation inherits its truncation
    flag. The `JsonlTrace` path is fixed at construction too, so a shared trace
    writes every item's events into the first item's directory and leaves the rest
    with no trace at all — the audit trail `CLAUDE.md` §6 requires.
    """
    if config.render_chart:
        raise FreezeMismatchError(
            "chart rendering must be off for a corpus run: 727 self-contained "
            "charts is ~3.3 GB of identical JavaScript that nothing scores"
        )

    done = ledger.completed()
    # Seeded from the ledger, not from zero. The allowance is a property of the
    # BAND — "2% of 356" — and a fresh count on every resume enforces it per
    # invocation instead: three resumes would tolerate 24 failures against an
    # allowance of 8 and never trip (ADR 0022). Six nights involve restarts, so
    # this is the difference between a threshold and a formality.
    health = _seed(Health(), ledger, band=items[0].band if items else "")
    consecutive = 0
    total = len(items)
    # An integer allowance, floored at one. Expressed as a bare rate, a short band
    # gives an allowance below 1 and halts on its first failure — arithmetically
    # correct and not what a 2% tolerance means.
    allowance = max(1, ceil(config.max_band_failure_rate * total))

    queue = execution_order(items, done, seed=config.execution_seed)
    for offset, item in enumerate(queue, start=1):
        # Position in the BAND, not in this invocation: a resume that shows
        # "[3/356]" after 200 completed items would misreport the run's progress.
        index = len(done) + offset

        started = time.monotonic()
        entry, error = _attempt(
            item,
            documents=documents,
            wiring=wiring,
            config=config,
            sleep=sleep,
        )
        entry = entry.model_copy(update={"elapsed_s": round(time.monotonic() - started, 1)})
        ledger.append(entry)
        _absorb(health, entry)

        if entry.status == "complete":
            consecutive = 0
        else:
            consecutive += 1
            _logger.warning(
                "corpus_item_failed",
                ticker=item.ticker,
                band=item.band,
                filing_date=str(item.filing_date),
                reason=entry.reason,
                detail=entry.detail[:200],
                consecutive=consecutive,
                cause=type(error).__name__ if error else None,
            )

        if on_progress is not None:
            on_progress(index, total, item, entry, health)
        _logger.info(
            "corpus_progress",
            band=item.band,
            done=f"{index}/{total}",
            completed=health.completed,
            failed=health.failed,
            fidelity_ok=health.fidelity_ok,
            unparseable=health.unparseable,
            divergent=health.divergent,
            ungrounded=health.ungrounded_numerals,
            degenerate_spread=health.degenerate_spread,
            budget_exhausted=health.budget_exhausted,
        )

        if consecutive >= config.max_consecutive_failures:
            raise CorpusHaltedError(f"{consecutive} consecutive failures", health.by_reason)
        if health.failed > allowance:
            raise CorpusHaltedError(
                f"{health.failed} failures exceeds the allowance of {allowance} "
                f"({config.max_band_failure_rate:.0%} of {total})",
                health.by_reason,
            )

    return health


def _attempt(
    item: CorpusItem,
    *,
    documents: Callable[[CorpusItem], tuple[Document, ...]],
    wiring: Callable[[UUID], Wiring],
    config: RunnerConfig,
    sleep: Callable[[float], None],
) -> tuple[LedgerEntry, MapError | None]:
    """One item, retried. Returns a terminal ledger entry either way.

    Fresh wiring per attempt, so the trace counts this item and nothing else.
    """
    last: MapError | None = None

    for attempt in range(config.attempts):
        try:
            run_id = new_run_id()
            built = wiring(run_id)
            result = execute(
                RunRequest(
                    run_id=run_id,
                    ticker=item.ticker,
                    horizon_days=config.horizon_days,
                    documents=documents(item),
                    history_days=config.history_days,
                    # Pinned to the filing, never a wall clock: a run crossing
                    # midnight must not shift the window it forecasts.
                    as_of=datetime.combine(item.filing_date, datetime.min.time(), tzinfo=UTC)
                    + timedelta(days=1),
                ),
                agents=built.agents,
                market=built.market,
                dividends=built.dividends,
                trace=built.trace,
                runs_dir=config.runs_dir,
                # Pinned so a multi-night run cannot silently refetch a new
                # vintage and mix adjustment bases mid-corpus (ADR 0012).
                today=config.price_vintage,
                render_chart=False,
                freeze_version=config.freeze_version,
                freeze_digest=(
                    config.freeze_digest_truncated
                    if item.key in TRUNCATION_NOTES
                    else config.freeze_digest
                ),
            )
            # Inside the try, so a missing artifact fails the item like any other
            # error. In the `else` clause it would escape the handlers entirely.
            _verify_artifacts(result.run_dir, str(result.forecast.run_id))
        except (InferenceUnreachableError, InferenceTimeoutError) as err:
            last = err
            if attempt < config.attempts - 1:
                sleep(config.backoff_s * (attempt + 1))
                continue
        except MapError as err:
            # Not transient: retrying a repair-exhausted forecast reproduces it.
            last = err
            break
        else:
            manifest = result.manifest
            return (
                LedgerEntry(
                    ticker=item.ticker,
                    band=item.band,
                    filing_date=item.filing_date,
                    status="complete",
                    run_id=result.forecast.run_id,
                    unparseable=len(manifest.fidelity.unparseable),
                    divergent=len(manifest.fidelity.divergent),
                    ungrounded_numerals=len(manifest.quality.ungrounded_numerals),
                    degenerate_spread=manifest.quality.degenerate_spread,
                    reasoning_tokens=sum(a.reasoning_tokens for a in manifest.agents),
                    cache_hits=sum(a.cache_hits for a in manifest.agents),
                    truncated=item.key in TRUNCATION_NOTES,
                    elided_chars=TRUNCATION_NOTES.get(item.key, 0),
                    output_truncated=any(a.output_truncated for a in manifest.agents),
                    truncated_agents=",".join(
                        a.alias for a in manifest.agents if a.output_truncated
                    ),
                    degeneration_retry=any(a.degeneration_retry for a in manifest.agents),
                    retried_agents=",".join(
                        a.alias for a in manifest.agents if a.degeneration_retry
                    ),
                ),
                None,
            )

    assert last is not None
    return (
        LedgerEntry(
            ticker=item.ticker,
            band=item.band,
            filing_date=item.filing_date,
            status="failed",
            reason=_reason_for(last),
            detail=str(last)[:300],
        ),
        last,
    )


def _seed(health: Health, ledger: Ledger, *, band: str) -> Health:
    """Fold this band's already-resolved items into the running health.

    Only *resolved* entries: a transient failure from an earlier pass is absent
    from `resolved()` and will be retried, so counting it would charge the
    allowance for a failure that may not survive the retry.
    """
    for entry in ledger.resolved().values():
        if entry.band == band:
            _absorb(health, entry)
    return health


def _absorb(health: Health, entry: LedgerEntry) -> None:
    if entry.status == "complete":
        health.completed += 1
        health.unparseable += entry.unparseable
        health.divergent += entry.divergent
        health.ungrounded_numerals += entry.ungrounded_numerals
        health.degenerate_spread += int(entry.degenerate_spread)
        health.output_truncated += int(entry.output_truncated)
        health.degeneration_retry += int(entry.degeneration_retry)
        health.reasoning_tokens += entry.reasoning_tokens
        health.cache_hits += entry.cache_hits
        return
    health.failed += 1
    reason = entry.reason or "other"
    health.by_reason[reason] = health.by_reason.get(reason, 0) + 1
    if reason == "budget_exhausted":
        health.budget_exhausted += 1
