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
from pathlib import Path
from uuid import UUID

import httpx

from mapf.agents.analyst import AnalystAgent
from mapf.agents.intake import IntakeAgent
from mapf.agents.structuralist import StructuralistAgent
from mapf.core.ports import DividendSource, LLMProvider, MarketDataProvider, ModelInfo
from mapf.data.cache import ParquetPriceCache
from mapf.data.earnings import EdgarEarningsCalendar
from mapf.data.filings import EdgarFilings
from mapf.data.providers.chain import ProviderChain
from mapf.data.providers.dividends import NullDividendSource, YFinanceDividendSource
from mapf.data.providers.stooq import StooqProvider
from mapf.data.providers.yfinance_provider import YFinanceProvider
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


def build_market_data(settings: Settings) -> MarketDataProvider:
    """The configured chain, behind the vintage-keyed parquet cache (ADR 0012)."""
    chain = ProviderChain([_PROVIDERS[name]() for name in settings.data.provider_order])
    return ParquetPriceCache(chain, settings.cache.price_dir)


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

    agents = Agents(
        intake=IntakeAgent(**common("intake")),  # type: ignore[arg-type]
        analyst=AnalystAgent(**common("analyst")),  # type: ignore[arg-type]
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
