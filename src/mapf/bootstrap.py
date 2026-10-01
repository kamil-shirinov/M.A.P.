"""Composition root.

The only module permitted to know which concrete adapters exist. It reads
settings, constructs implementations, and hands them upward as Protocols — which
is what lets every layer above depend on `mapf.core.ports` alone (ADR 0004).

Exempt from the `forbidden` contracts by design, and therefore the one place a
boundary breach can still hide. It stays small and free of logic for that reason:
everything here is construction, and any decision that needs a reason belongs in
the module that owns it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from uuid import UUID

import httpx

from mapf.agents.analyst import REALISED_VOL_TEMPLATE, AnalystAgent
from mapf.agents.intake import IntakeAgent
from mapf.agents.structuralist import StructuralistAgent
from mapf.core.ports import DividendSource, LLMProvider, MarketDataProvider, ModelInfo, QuoteSource
from mapf.data.cache import ParquetPriceCache, PriceSnapshot
from mapf.data.earnings import EdgarEarningsCalendar
from mapf.data.exhibits import EdgarExhibits
from mapf.data.filings import EdgarFilings
from mapf.data.providers.chain import ProviderChain
from mapf.data.providers.dividends import NullDividendSource, YFinanceDividendSource
from mapf.data.providers.stooq import StooqProvider
from mapf.data.providers.yfinance_provider import YFinanceProvider, YFinanceQuotes
from mapf.data.symbols import SqliteSymbolIndex, Throttle
from mapf.pipeline.run import TRACE_FILE, Agents
from mapf.pipeline.trace import CountingTrace, JsonlTrace
from mapf.prompts.loader import FilePromptStore
from mapf.providers.caching import CachingProvider
from mapf.providers.fake import FakeProvider
from mapf.providers.openai_compat import OpenAICompatProvider
from mapf.settings import ModelRegistry, Settings

_PROVIDERS = {"yfinance": YFinanceProvider, "stooq": StooqProvider}


def build_llm_provider(
    settings: Settings, *, fixtures: Path | None = None, cached: bool = True
) -> LLMProvider:
    """The live HTTP adapter behind a disk cache, or fixture replay.

    `fixtures` selects `FakeProvider`, which is why it ships in `src/` rather than
    in tests: the CLI can run offline against recorded fixtures.

    `cached=False` is for diagnostics. `map health` uses it because a cached probe
    would replay its own earlier answer and report on a server it never contacted —
    a health check that passes while the server is down is worse than none.
    """
    if fixtures is not None:
        return FakeProvider(fixtures)
    inner = OpenAICompatProvider(
        base_url=settings.inference.base_url,
        connect_timeout_s=settings.inference.connect_timeout_s,
        read_timeout_s=settings.inference.read_timeout_s,
    )
    return CachingProvider(inner, settings.cache.llm_dir) if cached else inner


def build_market_data(settings: Settings, *, vintage: date | None = None) -> MarketDataProvider:
    """The configured chain, behind the vintage-keyed parquet cache (ADR 0012).

    `vintage` pins the cache to a STORED SNAPSHOT and makes it read-only. Without it
    the cache namespaces on the calendar day, so every scoring run re-fetches and the
    corpus decays with every upstream revision.
    """
    chain = ProviderChain([_PROVIDERS[name]() for name in settings.data.provider_order])
    if vintage is None:
        return ParquetPriceCache(chain, settings.cache.price_dir)
    return ParquetPriceCache(chain, settings.cache.price_dir, today=lambda: vintage, frozen=True)


def build_quotes() -> QuoteSource:
    """The latest trade, for the local app's company page (ADR 0039). One source
    and no chain: a page can say "no quote" honestly, and a second provider's
    price beside the first's would be two answers to one question."""
    return YFinanceQuotes()


def build_price_snapshot(settings: Settings, vintage: date) -> PriceSnapshot:
    """Read-only access to one stored vintage.

    Not `build_market_data(settings, vintage=...)`: that returns a cache keyed on
    the exact window a run asked for, which cannot answer a question the run never
    asked. A five-session outcome is a bar the run's own snapshot could not contain
    — it did not exist yet — so it has to be looked up in a window stored later.
    """
    return PriceSnapshot(settings.cache.price_dir, vintage)


def build_dividends(settings: Settings) -> DividendSource:
    """ADR 0013. Yahoo when it is in the chain, otherwise an honest "unknown"."""
    if "yfinance" in settings.data.provider_order:
        return YFinanceDividendSource()
    return NullDividendSource()


def build_prompts() -> FilePromptStore:
    return FilePromptStore()


def build_earnings_calendar(settings: Settings, client: httpx.Client) -> EdgarEarningsCalendar:
    """The Item 2.02 calendar the multiplier baseline is fitted on (ADR 0023).

    Takes the client so the caller owns its lifetime: this is used inside `map
    evaluate`, which already opens one, and a second connection pool per adapter is
    a way to leak sockets over 356 items.
    """
    sec = settings.data.sec
    return EdgarEarningsCalendar(
        EdgarFilings(
            build_symbol_index(settings),
            user_agent=sec.user_agent,
            client=client,
            throttle=Throttle(sec.requests_per_second),
        ),
        cache_dir=settings.cache.earnings_dir,
    )


def build_filings(settings: Settings, client: httpx.Client) -> EdgarFilings:
    """Filing discovery for `map run --from-edgar`.

    The corpus never needs this — it reads accessions from the frozen record — so
    until now nothing outside `build_earnings_calendar` constructed one.
    """
    sec = settings.data.sec
    return EdgarFilings(
        build_symbol_index(settings),
        user_agent=sec.user_agent,
        client=client,
        throttle=Throttle(sec.requests_per_second),
    )


def build_exhibits(settings: Settings, client: httpx.Client) -> EdgarExhibits:
    """Exhibit fetching, for the same path.

    `corpus.py` built one inline because it was the only caller. A second caller is
    the point at which that belongs here instead.
    """
    sec = settings.data.sec
    return EdgarExhibits(
        user_agent=sec.user_agent,
        client=client,
        throttle=Throttle(sec.requests_per_second),
    )


def build_symbol_index(settings: Settings) -> SqliteSymbolIndex:
    return SqliteSymbolIndex(settings.data.sec.symbols_db)


def build_http_client(settings: Settings) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(
            connect=settings.inference.connect_timeout_s,
            read=settings.inference.read_timeout_s,
            write=settings.inference.connect_timeout_s,
            pool=settings.inference.connect_timeout_s,
        )
    )


@dataclass(frozen=True)
class Wiring:
    agents: Agents
    market: MarketDataProvider
    dividends: DividendSource
    trace: CountingTrace
    runs_dir: Path
    allow_nondeterministic: bool


def build_run(
    settings: Settings,
    *,
    provider: LLMProvider,
    resolved: dict[str, ModelInfo],
    run_id: UUID,
) -> Wiring:
    """Wire one run.

    The trace is wrapped **before** the agents are constructed: each agent holds
    its own reference, so a tap added afterwards would count nothing.
    """
    registry = ModelRegistry(settings.models)
    prompts = FilePromptStore()
    trace = CountingTrace(JsonlTrace(settings.paths.runs_dir / str(run_id) / TRACE_FILE))

    def common(stage: str) -> dict[str, object]:
        return {
            "provider": provider,
            "model": resolved[stage],
            "sampling": registry.spec(stage).sampling,  # type: ignore[arg-type]
            "prompts": prompts,
            "trace": trace,
            "stage": stage,
            "version": getattr(settings.prompts, stage),
            # So an oversized prompt is refused before dispatch, naming the agent
            # that produced it rather than arriving as an anonymous HTTP 400.
            "context_tokens": registry.spec(stage).context_tokens,  # type: ignore[arg-type]
            "upstream": registry.spec(stage).upstream,  # type: ignore[arg-type]
            # None for every agent that has no penalty configured, which disables
            # the retry entirely rather than applying a zero penalty (ADR 0021).
            "degeneration_penalty": registry.spec(stage).degeneration_penalty,  # type: ignore[arg-type]
        }

    analyst = common("analyst")
    if settings.experiments.analyst_realised_vol:
        # A2 (ADR 0042). Both change together or not at all, which is why this is one
        # branch and not two settings the user could set inconsistently.
        analyst = {
            **analyst,
            "template": REALISED_VOL_TEMPLATE,
            "version": settings.prompts.analyst_realised_vol,
        }
    agents = Agents(
        intake=IntakeAgent(**common("intake")),  # type: ignore[arg-type]
        analyst=AnalystAgent(**analyst),  # type: ignore[arg-type]
        structuralist=StructuralistAgent(
            **common("structuralist"),  # type: ignore[arg-type]
            max_attempts=settings.inference.max_repair_attempts,
        ),
    )
    return Wiring(
        agents=agents,
        market=build_market_data(settings),
        dividends=build_dividends(settings),
        trace=trace,
        runs_dir=settings.paths.runs_dir,
        allow_nondeterministic=settings.models.allow_nondeterministic,
    )
