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

    def __init__(self, key: str, value: str, hint: str | None = None) -> None:
        self.key = key
        self.value = value
        self.hint = hint
        message = f"config key {key!r} still holds its placeholder value {value!r}"
        # The hint is where the *actionable* half lives — which env var to set and
        # what a correct value looks like. A config error without it just tells the
        # operator they are wrong.
        super().__init__(f"{message}. {hint}" if hint else message)


class DeterminismPolicyError(ConfigurationError):
    """An agent required to be deterministic was configured with sampling.

    `CLAUDE.md` §6 lists `temperature=0` for Agents 1 and 3 as a non-negotiable.
    Enforced rather than documented, because the damage is invisible: a run with
    a sampling structuralist still produces a valid forecast, and only the
    inability to reproduce it later reveals the problem.
    """

    def __init__(self, agent: str, temperature: float) -> None:
        self.agent = agent
        self.temperature = temperature
        super().__init__(
            f"agent {agent!r} must run at temperature 0.0 for reproducibility, "
            f"but is configured with {temperature!r}. Either set "
            f"models.{agent}.temperature = 0.0, or — if the non-determinism is "
            "deliberate — set models.allow_nondeterministic = true, which permits it, "
            "warns at startup, and marks every affected run in its manifest."
        )


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------
class ProviderError(MapError):
    """An external dependency failed."""


class InferenceError(ProviderError):
    """The inference server failed to produce a usable response."""


class InferenceUnreachableError(InferenceError):
    """No connection was accepted. The server is not running, or not there.

    Kept strictly separate from a timeout (ADR 0008). "The server is down" and
    "the model is still loading" have completely different remedies, and on this
    hardware the second is routine.
    """

    def __init__(self, base_url: str, reason: str) -> None:
        self.base_url = base_url
        self.reason = reason
        super().__init__(
            f"no inference server accepted a connection at {base_url} ({reason}). "
            "Start the backend, or check inference.base_url."
        )


class InferenceTimeoutError(InferenceError):
    """Connected, but no complete response arrived within the read timeout.

    On 16 GB the backend loads weights on demand, so the most likely cause is a
    cold model load rather than a hung server — a 12B can take 30 s or more before
    the first token. Raising the same error as an unreachable server would make
    every slow first call look like a bug.
    """

    def __init__(self, model_id: str, read_timeout_s: float) -> None:
        self.model_id = model_id
        self.read_timeout_s = read_timeout_s
        super().__init__(
            f"no response for model {model_id!r} within {read_timeout_s}s. The server is "
            "reachable, so this is most likely a cold model load. Raise "
            "inference.read_timeout_s, or pre-load the model."
        )


class InferenceStatusError(InferenceError):
    """The server answered with a non-2xx status that is not a missing model."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"inference server returned HTTP {status_code}: {body[:300]}")


class InferenceProtocolError(InferenceError):
    """The server answered, but not in the shape the OpenAI-compatible API defines."""


class FixtureNotFoundError(ProviderError):
    """The fake provider has no recording for this request.

    Names the key and what is available, because the usual cause is a prompt or
    sampling change that silently moved the key — and a bare KeyError would send
    someone hunting through the fixture directory by hand.
    """

    def __init__(self, key: str, fixture_dir: str, available: Sequence[str]) -> None:
        self.key = key
        self.fixture_dir = fixture_dir
        self.available = tuple(available)
        shown = ", ".join(self.available[:5]) if self.available else "(none)"
        super().__init__(
            f"no fixture {key} in {fixture_dir} ({len(self.available)} present: {shown}"
            f"{', ...' if len(self.available) > 5 else ''}). The request changed, or the "
            "fixture was never recorded."
        )


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
