"""Agent ordering, artifact assembly, and the run manifest.

Parameterised entirely by Protocols and already-constructed agents. It imports
neither `providers` nor `data` — `import-linter` enforces that (ADR 0004) — which
is what lets the whole pipeline be built against `FakeProvider` with no HTTP
client anywhere in the import graph. That is DoD criterion 6, holding end to end
rather than only for unit tests.

The agents run strictly in sequence, and on 16 GB that is not stylistic: each swap
unloads one model and loads the next, so two are never resident (`CLAUDE.md` §3).
A cold run therefore pays three model loads, which is why the cache is
infrastructure rather than an optimisation.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import structlog

from mapf.agents.analyst import AnalystAgent, AnalystRequest
from mapf.agents.base import LLMAgent
from mapf.agents.intake import IntakeAgent, IntakeRequest
from mapf.agents.structuralist import StructuralistAgent, StructuralistRequest
from mapf.core.hashing import new_run_id
from mapf.core.models import (
    Document,
    DocumentId,
    Forecast,
    ModelVersions,
    PriceWindow,
    ScenarioSet,
)
from mapf.core.ports import DividendSource, MarketDataProvider
from mapf.core.quality import check as check_quality
from mapf.pipeline.manifest import AgentRecord, PriceProvenance, RunManifest
from mapf.pipeline.trace import CountingTrace
from mapf.render.chart import write_chart

_logger = structlog.get_logger(__name__)

PACKAGE_VERSION = "0.1.0"

FORECAST_FILE = "forecast.json"
MANIFEST_FILE = "manifest.json"
TRACE_FILE = "trace.jsonl"
CHART_FILE = "chart.html"


@dataclass(frozen=True)
class RunRequest:
    ticker: str
    horizon_days: int
    documents: tuple[Document, ...]
    history_days: int = 730
    run_id: UUID | None = None
    as_of: datetime | None = None


@dataclass(frozen=True)
class Agents:
    """The three agents, already constructed. `bootstrap` builds these."""

    intake: IntakeAgent
    analyst: AnalystAgent
    structuralist: StructuralistAgent


@dataclass(frozen=True)
class RunResult:
    forecast: Forecast
    manifest: RunManifest
    window: PriceWindow
    scenarios: ScenarioSet
    run_dir: Path


def _record(agent: LLMAgent, trace: CountingTrace) -> AgentRecord:
    stage = agent.stage
    name, version, digest = trace.templates.get(stage, ("unknown", "unknown", "0" * 64))
    return AgentRecord(
        alias=stage,
        model_id=agent.model.id,
        fingerprint=agent.model.fingerprint,
        fingerprint_source=agent.model.fingerprint_source,
        fingerprint_fields=agent.model.fingerprint_fields,
        sampling=agent.sampling,
        template_name=name,
        template_version=version,
        template_sha256=digest,
        attempts=trace.attempts.get(stage, 1),
        cache_hits=trace.cache_hits.get(stage, 0),
    )


def execute(
    request: RunRequest,
    *,
    agents: Agents,
    market: MarketDataProvider,
    dividends: DividendSource,
    trace: CountingTrace,
    runs_dir: Path,
    allow_nondeterministic: bool = False,
    today: date | None = None,
) -> RunResult:
    """Run the pipeline once and write every artifact.

    `trace` must be the same `CountingTrace` the agents were constructed with, or
    the manifest's attempt and cache-hit counts will all be zero.
    """
    run_id = request.run_id or new_run_id()
    as_of = request.as_of or datetime.now(UTC)
    fetched_on = today or as_of.date()

    # 1. Prices. `last_trading_date` — never a wall clock — is what reaches prompts.
    end = as_of.date()
    window = market.get_ohlcv(request.ticker, end - timedelta(days=request.history_days), end)
    as_of_date = window.last_trading_date
    spot = window.last_close

    # 2. Agents, strictly in sequence: one model resident at a time.
    facts = agents.intake.run(
        IntakeRequest(ticker=request.ticker, as_of_date=as_of_date, documents=request.documents)
    )
    narrative = agents.analyst.run(
        AnalystRequest(
            ticker=request.ticker,
            as_of_date=as_of_date,
            horizon_days=request.horizon_days,
            facts=facts,
        )
    )
    scenarios = agents.structuralist.run(StructuralistRequest(narrative=narrative))

    # 3. Assemble. The model authored `scenarios` and nothing else (ADR 0002) —
    #    every other field here is something the pipeline already knew.
    forecast = Forecast(
        run_id=run_id,
        ticker=request.ticker,
        as_of=as_of,
        horizon_days=request.horizon_days,
        spot_price=spot,
        source_doc_ids=tuple(DocumentId(document.id) for document in request.documents),
        model_versions=ModelVersions(
            intake=agents.intake.model.fingerprint,
            analyst=agents.analyst.model.fingerprint,
            structuralist=agents.structuralist.model.fingerprint,
        ),
        scenarios=scenarios,
    )

    # 4. Ex-dividend flag over the forecast window (ADR 0013). Never blocks a run;
    #    an unavailable calendar reports `known=False`, which Phase 2 must read as
    #    "unknown" rather than "none".
    dividend_window = dividends.dividends_in(
        request.ticker, as_of_date, as_of_date + timedelta(days=request.horizon_days)
    )

    # Soft checks. Neither can reject a forecast; both must stop it passing silently.
    quality = check_quality(scenarios, horizon_days=request.horizon_days, facts=facts.facts)
    if quality.degenerate_spread:
        _logger.warning(
            "degenerate_spread",
            ticker=request.ticker,
            spread=quality.spread,
            floor=quality.spread_floor,
            horizon_days=request.horizon_days,
            note="three scenarios within a hair of each other are not three scenarios",
        )
    if quality.ungrounded_numerals:
        _logger.warning(
            "ungrounded_numerals",
            ticker=request.ticker,
            values=list(quality.ungrounded_numerals),
            note="figures in a justification that trace to no material fact",
        )

    manifest = RunManifest(
        run_id=run_id,
        ticker=request.ticker,
        as_of=as_of,
        horizon_days=request.horizon_days,
        spot_price=spot,
        source_doc_ids=forecast.source_doc_ids,
        agents=(
            _record(agents.intake, trace),
            _record(agents.analyst, trace),
            _record(agents.structuralist, trace),
        ),
        prices=PriceProvenance(
            provider=window.provider,
            adjustment=window.adjustment,
            fetched_on=fetched_on,
            window_start=window.bars[0].date,
            window_end=window.bars[-1].date,
            last_trading_date=as_of_date,
            bars=len(window.bars),
        ),
        dividends=dividend_window,
        quality=quality,
        allow_nondeterministic=allow_nondeterministic,
        package_version=PACKAGE_VERSION,
        python_version=platform.python_version(),
    )

    run_dir = runs_dir / str(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / FORECAST_FILE).write_text(forecast.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / MANIFEST_FILE).write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    write_chart(window, forecast, run_dir / CHART_FILE)

    return RunResult(
        forecast=forecast,
        manifest=manifest,
        window=window,
        scenarios=scenarios,
        run_dir=run_dir,
    )
