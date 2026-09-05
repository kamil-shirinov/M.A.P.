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


class UnreachableTokenBudgetError(ConfigurationError):
    """A token budget that cannot be spent before the read timeout fires.

    `max_tokens` and `read_timeout_s` are set independently and mean nothing to
    each other, but the hardware couples them: a budget the model cannot finish
    spending in time is not a budget, it is a timeout wearing one. A run that
    actually reached it would fail as `InferenceTimeoutError` and send the reader
    looking for a cold model load that never happened.

    The same class of defect as a manifest field that does not mean what its name
    says: a limit that claims one thing and enforces another.
    """

    def __init__(
        self,
        agent: str,
        max_tokens: int,
        read_timeout_s: float,
        tokens_per_second: float,
        margin: float,
    ) -> None:
        self.agent = agent
        self.max_tokens = max_tokens
        needed = max_tokens / tokens_per_second
        super().__init__(
            f"agent {agent!r} may generate {max_tokens} tokens, which at "
            f"{tokens_per_second:g} tok/s takes about {needed:.0f}s — beyond "
            f"{margin:.0%} of inference.read_timeout_s ({read_timeout_s:g}s). "
            f"Lower models.{agent}.max_tokens, raise inference.read_timeout_s, or "
            "correct inference.min_tokens_per_second if this machine is faster."
        )


class UnreachableContextBudgetError(ConfigurationError):
    """`max_tokens` does not fit inside the agent's context window.

    Generation shares the window with the prompt, so a budget at or above the
    context can never be spent: the model stops at the context ceiling and reports
    exhaustion, which reads as "the prompt was too long for the model to answer"
    when the truth is "these two numbers were set independently and contradict".
    That is exactly how the first corpus run failed on TSLA — 6,699 reasoning
    tokens against a 12,000 budget in an 8,192 window.
    """

    def __init__(self, agent: str, max_tokens: int, context_tokens: int) -> None:
        self.agent = agent
        self.max_tokens = max_tokens
        self.context_tokens = context_tokens
        super().__init__(
            f"{agent}: max_tokens={max_tokens:,} does not fit in context_tokens="
            f"{context_tokens:,}. Generation shares the window with the prompt, so "
            f"the budget is unreachable and the model will stop at the context "
            f"ceiling while reporting budget exhaustion. Raise the context or lower "
            f"the budget."
        )


class ChainBudgetError(ConfigurationError):
    """One agent's maximum output cannot fit the next agent's input window.

    Agents were validated in isolation, each budget against its own context, and
    the *chain* between them was never checked. Intake then emitted ~20,000 tokens
    from a 12,500-token document — it expanded rather than compressed — and the
    analyst rejected a 22,368-token prompt against its 16,384 window. Both agents
    were individually valid; the pipeline they form was not.
    """

    def __init__(
        self,
        upstream: str,
        downstream: str,
        produced: int,
        overhead: int,
        reserved: int,
        window: int,
    ) -> None:
        self.upstream, self.downstream = upstream, downstream
        super().__init__(
            f"{upstream} may emit {produced:,} tokens, but {downstream} can accept "
            f"only {window - overhead - reserved:,} "
            f"(window {window:,} less {overhead:,} template and {reserved:,} "
            f"generation). Lower {upstream}'s max_tokens, raise {downstream}'s "
            f"context_tokens, or lower {downstream}'s generation budget."
        )


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


class ModelBudgetExhaustedError(InferenceError):
    """The model spent its whole token budget and emitted no answer.

    Distinct from a refusal and from a protocol error, because the remedy is
    different and because the alternative message actively misleads. A
    reasoning-capable model streams into a separate `reasoning_content` field and
    only then writes its answer; if the budget runs out first, `content` is empty
    while thousands of tokens were generated.

    Reported as "too short; likely a refusal" — which is what happened before this
    existed — it sends the reader to the prompt's *content* when the problem is its
    *length*.
    """

    def __init__(
        self,
        model_id: str,
        completion_tokens: int,
        reasoning_tokens: int,
        reasoning_text: str = "",
    ) -> None:
        self.model_id = model_id
        self.completion_tokens = completion_tokens
        self.reasoning_tokens = reasoning_tokens
        # What the model actually produced before it ran out. Carried on the error
        # because this is the ONLY place it exists: the call raises before any
        # response object is built, so without it the failure that most needs
        # diagnosing is the one that leaves nothing behind (ADR 0027).
        self.reasoning_text = reasoning_text
        super().__init__(
            f"{model_id} generated {completion_tokens} tokens "
            f"({reasoning_tokens} of them reasoning) and produced no answer: the "
            "token budget ran out before it finished thinking. Raise max_tokens for "
            "this agent, shorten its prompt, or use a build that does not reason."
        )


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


class MalformedPriceDataError(MarketDataError):
    """A provider returned rows that cannot be a price series.

    An open outside [low, high] is impossible, not merely surprising, and it is
    the shape upstream corruption actually takes: on 2026-09-04 Yahoo served five
    tickers with `open` above `high` for a few hours and then corrected them.

    Distinct from `EmptyPriceWindowError`: the provider answered, and the answer
    is invalid. A `MarketDataError` so the chain FAILS OVER rather than dying —
    a provider serving impossible data is precisely what a fallback exists for,
    and before this the validation failure escaped `ProviderChain` entirely and
    killed the run with a second provider configured and untried.
    """

    def __init__(self, provider: str, ticker: str, reason: str) -> None:
        self.provider = provider
        self.ticker = ticker
        self.reason = reason
        super().__init__(f"{provider} returned unusable bars for {ticker}: {reason}")


class PriceSnapshotIncompleteError(MarketDataError):
    """A pinned price vintage does not hold the window a score needs.

    Raised instead of fetching. A vintage that silently backfills from today is not
    a snapshot — it is the calendar-keyed cache with a fixed name, and it reintroduces
    exactly the decay it was added to stop: on 2026-09-05 Yahoo rewrote SCCO's
    split-adjusted close from 204.2374 to 201.8156, retroactively, and three corpus
    items stopped matching the spot they were produced against.
    """

    def __init__(self, ticker: str, vintage: str, window: str) -> None:
        self.ticker = ticker
        self.vintage = vintage
        self.window = window
        super().__init__(
            f"price snapshot {vintage} has no window {window} for {ticker}; "
            "a pinned vintage never fetches"
        )


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
# Prompts
# ---------------------------------------------------------------------------
class ExhibitError(ProviderError):
    """An Item 2.02 exhibit could not be retrieved.

    Covers the answers EDGAR actually gave: a 404, a 500, a malformed document. The
    server was reached and refused or returned something unusable, which is a fact
    about the filing or about EDGAR's view of it — the same fact on the next pass.
    """


class ExhibitUnreachableError(ExhibitError):
    """EDGAR was never reached: DNS, a refused connection, a dropped socket.

    Split from `ExhibitError` because the two say opposite things about the ITEM. A
    404 is a property of the filing; a DNS failure is a property of the afternoon,
    and five items failing together says only that the network went away.

    The distinction became load-bearing with the repeat rule (ADR 0024): a reason
    that recurs is treated as terminal for that item, and a shared outage spanning
    two resumes would otherwise burn every item it touched. It is excluded for the
    same reason `inference_unreachable` is.
    """


class MissingExhibitError(ExhibitError):
    """The filing carries no usable Exhibit 99.1.

    Terminal rather than transient, and the distinction is load-bearing: a filing
    without an exhibit has none on the next resume either, so retrying it would
    consume the run's failure threshold afresh every pass and eventually halt on
    an item that can never succeed (ADR 0019).
    """


class PromptTooLargeError(ProviderError):
    """A rendered prompt exceeds the receiving agent's verified window.

    Raised before dispatch, so the failure names the agent that produced the
    oversized payload and how large it was. A raw HTTP 400 from the server says
    only that something did not fit, which is the least useful moment to learn it.
    """

    def __init__(
        self, agent: str, upstream: str | None, tokens: int, allowance: int, window: int
    ) -> None:
        self.agent, self.upstream = agent, upstream
        self.tokens, self.allowance = tokens, allowance
        source = f" produced by {upstream}" if upstream else ""
        super().__init__(
            f"{agent} was handed a prompt of ~{tokens:,} tokens{source}, but can "
            f"accept only {allowance:,} (window {window:,} less its generation "
            f"budget). Refused before dispatch."
        )


class MissingArtifactError(MapError):
    """A run reported success but did not leave the artifacts to prove it.

    The rule was "append to the ledger only after every artifact has landed", and
    it was enforced by *ordering* alone — the append happened last, so the writes
    were assumed to have happened. A shared trace then wrote every item's events
    into the first item's directory, and 56 of 57 runs were recorded complete with
    no `trace.jsonl` at all. Full provenance is the project's central claim and it
    was silently absent for 98% of a run.

    Ordering is not verification. This checks.
    """

    def __init__(self, run_id: str, missing: Sequence[str]) -> None:
        self.run_id, self.missing = run_id, tuple(missing)
        super().__init__(
            f"run {run_id} produced no usable {', '.join(missing)}. A forecast whose "
            f"provenance is absent is not a forecast that can be audited, so the "
            f"item is failed rather than recorded complete."
        )


class PromptError(MapError):
    """A prompt could not be loaded or rendered."""


class TemplateNotFoundError(PromptError):
    def __init__(self, name: str, version: str, available: Sequence[str]) -> None:
        self.name = name
        self.version = version
        self.available = tuple(available)
        listed = ", ".join(self.available) if self.available else "(none)"
        super().__init__(f"no prompt template {name}.{version}.md; available: {listed}")


class TemplateFormatError(PromptError):
    """A template file is not a sequence of role-marked sections."""


class PromptSlotError(PromptError):
    """A slot was missing, unknown, or supplied as both trusted and untrusted.

    Unknown slots are an error rather than a no-op: the usual cause is a typo, and
    silently rendering a prompt with a placeholder left in it would send that
    placeholder to the model as if it were content.
    """


class PromptSanitisationError(PromptError):
    """Untrusted text could not be made safe to interpolate.

    Should be unreachable — the neutralisation loop shrinks its input on every
    pass, so it terminates. It raises rather than returning partly-cleaned text,
    because the alternative is emitting a prompt whose quarantine may not hold.
    """


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------
class SymbolError(MapError):
    """Base for symbol resolution failures."""


class SymbolIndexMissingError(SymbolError):
    """The local symbol index has not been built.

    Search is deliberately offline and pure: it never syncs as a side effect,
    because a search that silently fetches breaks the offline guarantee and turns
    an EDGAR 403 into a mysterious hang inside what looked like a local lookup.
    So the remedy is named instead.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(
            f"no symbol index at {path}. Build it once with `map symbols sync`; "
            "search never downloads on its own."
        )


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
# News
# ---------------------------------------------------------------------------
class NewsError(MapError):
    """News could not be loaded."""


class NewsSourceUnavailableError(NewsError):
    """A feed or directory could not be read."""

    def __init__(self, source: str, reason: str) -> None:
        self.source = source
        self.reason = reason
        super().__init__(f"cannot read news source {source!r}: {reason}")


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
class AgentError(MapError):
    """An agent could not meet its contract."""


class OutputTruncatedError(AgentError):
    """An agent stopped at its token cap instead of finishing.

    Raised rather than warned, because what it hands downstream is a fragment
    presented as a whole: a fact list ending mid-sentence still produces a
    schema-valid forecast, scored beside forecasts built on complete summaries.

    Measured, this is not a sizing problem. Intake emits 252–543 tokens across
    documents from 2k to 51k characters — remarkably flat — and then on two
    documents runs away past 18,000 with no sign of stopping. A cap sized to
    "what it wants" is meaningless when what it wants is unbounded, so the cap
    bounds the runaway and this makes the runaway visible.
    """

    def __init__(self, agent: str, tokens: int) -> None:
        self.agent, self.tokens = agent, tokens
        super().__init__(
            f"{agent} stopped at its {tokens:,}-token cap rather than finishing, so "
            f"what it produced is a fragment. Typical output is a few hundred "
            f"tokens; this is a runaway, and the item is failed rather than scored "
            f"on a partial summary."
        )


class NoMaterialFactsError(AgentError):
    """Agent 1 found nothing material in the documents.

    A legitimate outcome — the template explicitly permits an empty answer rather
    than inviting fabrication — but not one a forecast can be built on. Raising is
    the honest response: the alternative is a forecast derived from nothing, which
    would be indistinguishable from a real one downstream.
    """

    def __init__(self, ticker: str, documents: int) -> None:
        self.ticker = ticker
        self.documents = documents
        super().__init__(
            f"no material facts extracted for {ticker} from {documents} document(s). "
            "The source material may genuinely contain nothing material; a forecast "
            "cannot be built from it either way."
        )


class AnalystOutputError(AgentError):
    """Agent 2 returned something that is not a narrative.

    The only check available. Prose cannot be schema-validated, so this catches
    refusals, truncation, and empty responses — nothing more.
    """

    def __init__(self, reason: str, length: int) -> None:
        self.reason = reason
        self.length = length
        super().__init__(f"analyst output rejected ({reason}); length was {length} characters")


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
