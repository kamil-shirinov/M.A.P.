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

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from math import ceil
from pathlib import Path

import structlog

from mapf.core.errors import (
    ForecastRepairExhausted,
    InferenceTimeoutError,
    InferenceUnreachableError,
    MapError,
    MarketDataError,
    MissingExhibitError,
    ModelBudgetExhaustedError,
    NoMaterialFactsError,
)
from mapf.core.models import Document
from mapf.core.ports import DividendSource, MarketDataProvider
from mapf.corpus.ledger import FailureReason, Ledger, LedgerEntry
from mapf.corpus.selection import Corpus
from mapf.pipeline.run import Agents, RunRequest, execute
from mapf.pipeline.trace import CountingTrace

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


def verify_freeze(
    frozen: Mapping[str, object],
    *,
    live_digest: Callable[[str, str], str],
    live_models: Mapping[str, str],
) -> None:
    """Check live templates and models against the frozen record, or refuse.

    `live_digest(name, version)` hashes the template as it exists now.
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
            expected = str(spec.get("alias", ""))
            actual_alias = live_models.get(agent)
            if actual_alias is not None and actual_alias != expected:
                mismatches.append(
                    f"{agent}: model alias is {actual_alias!r}, frozen as {expected!r}"
                )

    if mismatches:
        raise FreezeMismatchError(
            "live configuration differs from the frozen corpus — every cache key is "
            "invalidated and the run would cost the full budget again:\n  "
            + "\n  ".join(mismatches)
        )


def _reason_for(error: MapError) -> FailureReason:
    if isinstance(error, MissingExhibitError):
        return "missing_exhibit"
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


@dataclass(frozen=True)
class RunnerConfig:
    runs_dir: Path
    price_vintage: date
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
    agents: Agents,
    market: MarketDataProvider,
    dividends: DividendSource,
    trace: CountingTrace,
    ledger: Ledger,
    config: RunnerConfig,
    sleep: Callable[[float], None] = time.sleep,
) -> Health:
    """Execute one band, resuming from the ledger and halting on threshold.

    Raises `CorpusHaltedError` when a threshold is crossed. Everything completed
    up to that point is already durable — the ledger is appended per item — so a
    halt costs the diagnosis, never the work.
    """
    if config.render_chart:
        raise FreezeMismatchError(
            "chart rendering must be off for a corpus run: 727 self-contained "
            "charts is ~3.3 GB of identical JavaScript that nothing scores"
        )

    done = ledger.completed()
    health = Health()
    consecutive = 0
    total = len(items)
    # An integer allowance, floored at one. Expressed as a bare rate, a short band
    # gives an allowance below 1 and halts on its first failure — arithmetically
    # correct and not what a 2% tolerance means.
    allowance = max(1, ceil(config.max_band_failure_rate * total))

    for index, item in enumerate(items, start=1):
        if item.key in done:
            continue

        started = time.monotonic()
        entry, error = _attempt(
            item,
            documents=documents,
            agents=agents,
            market=market,
            dividends=dividends,
            trace=trace,
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
            raise CorpusHaltedError(
                f"{consecutive} consecutive failures", health.by_reason
            )
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
    agents: Agents,
    market: MarketDataProvider,
    dividends: DividendSource,
    trace: CountingTrace,
    config: RunnerConfig,
    sleep: Callable[[float], None],
) -> tuple[LedgerEntry, MapError | None]:
    """One item, retried. Returns a terminal ledger entry either way."""
    last: MapError | None = None

    for attempt in range(config.attempts):
        try:
            result = execute(
                RunRequest(
                    ticker=item.ticker,
                    horizon_days=config.horizon_days,
                    documents=documents(item),
                    history_days=config.history_days,
                    # Pinned to the filing, never a wall clock: a run crossing
                    # midnight must not shift the window it forecasts.
                    as_of=datetime.combine(item.filing_date, datetime.min.time(), tzinfo=UTC)
                    + timedelta(days=1),
                ),
                agents=agents,
                market=market,
                dividends=dividends,
                trace=trace,
                runs_dir=config.runs_dir,
                # Pinned so a multi-night run cannot silently refetch a new
                # vintage and mix adjustment bases mid-corpus (ADR 0012).
                today=config.price_vintage,
                render_chart=False,
            )
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


def _absorb(health: Health, entry: LedgerEntry) -> None:
    if entry.status == "complete":
        health.completed += 1
        health.unparseable += entry.unparseable
        health.divergent += entry.divergent
        health.ungrounded_numerals += entry.ungrounded_numerals
        health.degenerate_spread += int(entry.degenerate_spread)
        health.reasoning_tokens += entry.reasoning_tokens
        health.cache_hits += entry.cache_hits
        return
    health.failed += 1
    reason = entry.reason or "other"
    health.by_reason[reason] = health.by_reason.get(reason, 0) + 1
    if reason == "budget_exhausted":
        health.budget_exhausted += 1
