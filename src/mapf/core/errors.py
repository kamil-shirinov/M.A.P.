"""Typed failures.

Why a hierarchy rather than `ValueError` with a good message: the failover chain
and the repair loop both need to *branch* on what went wrong. A chain that
catches broad exceptions cannot distinguish "this provider is throttled, try the
next one" from "this ticker does not exist, trying the next one is pointless" —
and would quietly turn the second into a wasted round trip and a misleading
manifest.

`CLAUDE.md` §7 bans bare `except:`. This module is what makes that practical.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


class MapError(Exception):
    """Base for every error this project raises deliberately."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
class ConfigurationError(MapError):
    """The system cannot start as configured. Always fatal, never retried."""


class ModelNotAvailableError(ConfigurationError):
    """A configured model alias is not loaded on the server.

    Fails fast at startup with the list actually available, because the common
    cause is a naming difference between backends rather than a missing download.
    """

    def __init__(self, alias: str, available: Sequence[str]) -> None:
        self.alias = alias
        self.available = tuple(available)
        listed = ", ".join(self.available) if self.available else "(none)"
        super().__init__(f"model alias {alias!r} is not loaded; server reports: {listed}")


class PlaceholderConfigError(ConfigurationError):
    """A shipped placeholder was never replaced.

    Exists so the SEC User-Agent placeholder fails at startup rather than as a
    403 and a ten-minute IP block halfway through a symbol download.
    """

    def __init__(self, key: str, value: str) -> None:
        self.key = key
        self.value = value
        super().__init__(f"config key {key!r} still holds its placeholder value {value!r}")


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------
class ProviderError(MapError):
    """An external dependency failed."""


class InferenceError(ProviderError):
    """The inference server failed to produce a usable response."""


class InferenceTimeoutError(InferenceError):
    """Distinguished from a protocol error because a 12B model swap is slow.

    A timeout here is often a cold model load, not a broken server.
    """


class InferenceProtocolError(InferenceError):
    """The server answered, but not in the shape the OpenAI-compatible API defines."""


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------
class MarketDataError(ProviderError):
    """Base for price-source failures."""


class MarketDataUnavailableError(MarketDataError):
    """This provider cannot serve right now — throttled, down, or scraper-broken.

    The one failure the chain treats as a reason to fall back. yfinance is an
    unofficial scraper and throttles at roughly 950 requests per session, so this
    is an expected condition, not an exceptional one (ADR 0003).
    """

    def __init__(self, provider: str, reason: str) -> None:
        self.provider = provider
        self.reason = reason
        super().__init__(f"{provider} unavailable: {reason}")


class AllMarketDataProvidersFailedError(MarketDataError):
    """Every provider in the chain failed. Carries each cause for the trace."""

    def __init__(self, causes: Mapping[str, BaseException]) -> None:
        self.causes = dict(causes)
        detail = "; ".join(f"{name}: {err}" for name, err in self.causes.items())
        super().__init__(f"all market-data providers failed -- {detail}")


class EmptyPriceWindowError(MarketDataError):
    """A provider returned no rows for a range it claimed to serve.

    Never silently returned as an empty frame: a zero-length series looks
    plausible everywhere downstream and produces a forecast against nothing.
    """

    def __init__(self, provider: str, ticker: str) -> None:
        self.provider = provider
        self.ticker = ticker
        super().__init__(f"{provider} returned no bars for {ticker}")


class PriceAdjustmentUnsupportedError(MarketDataError):
    """The adapter cannot produce the canonical adjustment basis for this request.

    Failing is correct. Serving an unadjusted series where an adjusted one was
    promised silently contaminates every score computed across the boundary.
    """

    def __init__(self, provider: str, requested: str) -> None:
        self.provider = provider
        self.requested = requested
        super().__init__(f"{provider} cannot produce adjustment basis {requested!r}")


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------
class SymbolError(MapError):
    """Base for symbol resolution failures."""


class SymbolNotFoundError(SymbolError):
    def __init__(self, query: str) -> None:
        self.query = query
        super().__init__(
            f"no symbol matches {query!r}. Name search covers US-listed companies only; "
            "pass a suffixed ticker directly for other venues"
        )


class AmbiguousSymbolError(SymbolError):
    """Several candidates matched. Carries them; the caller must choose.

    Guessing here would attach a forecast to the wrong company, which is exactly
    the kind of error that looks like a working system.
    """

    def __init__(self, query: str, candidates: Sequence[str]) -> None:
        self.query = query
        self.candidates = tuple(candidates)
        super().__init__(f"{query!r} is ambiguous between: {', '.join(self.candidates)}")


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
class AgentError(MapError):
    """An agent could not meet its contract."""


# N818 wants an `Error` suffix. The name is fixed by the design review and reads
# better at the call site (`except ForecastRepairExhausted`), so the rule is waived
# here rather than the name bent to satisfy it.
class ForecastRepairExhausted(AgentError):  # noqa: N818
    """Agent 3 failed validation on every attempt.

    Raised rather than returning a coerced or partial object. A forecast that was
    patched into validity by the pipeline is not the model's forecast, and
    scoring it in Phase 2 would measure the patch.

    Carries the last raw response so the trace shows what the model actually
    emitted, not merely that it was wrong.
    """

    def __init__(self, attempts: int, errors: Sequence[str], last_response: str) -> None:
        self.attempts = attempts
        self.errors = tuple(errors)
        self.last_response = last_response
        joined = "; ".join(self.errors)
        super().__init__(f"structuralist failed validation after {attempts} attempt(s): {joined}")
