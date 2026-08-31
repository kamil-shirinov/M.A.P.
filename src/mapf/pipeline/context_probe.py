"""Measure the server's real context window by bracketing it.

The first corpus run failed because `config/default.toml` and the inference server
disagreed and nothing compared them. A pre-flight that checked a configured number
against a computed one would have passed it happily: both were internally
consistent, and neither was the server.

Context length is a *server-side* setting, in exactly the sense KV-cache
quantisation is — invisible to the cache key, invisible to the model fingerprint,
able to change what the model does without changing anything this repository can
see. So it is measured, like the grammar probe measures constrained decoding.

**The measurement is a bracket, not a parsed error message.** Two requests per
agent: one sized just under the configured window, which must be accepted, and one
comfortably over, which must be rejected. That pins the window without the server
ever naming a number, and it works on any backend. Reading the size out of an error
string would depend on how one particular server phrases itself, which is the
vendor coupling `CLAUDE.md` §3 forbids in application code; a parsed number is kept
only as an optional refinement when one happens to be present.

The filler is a repeated common word, so the token count is close to the word count
on any byte-pair vocabulary. That is what lets the probe target a size directly
rather than through a characters-per-token ratio it would have to assume.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mapf.core.errors import (
    InferenceError,
    InferenceStatusError,
    ModelBudgetExhaustedError,
)
from mapf.core.ports import (
    LLMProvider,
    Message,
    ModelInfo,
    RenderedPrompt,
    SamplingParams,
)

# One very common token, repeated. Chosen so the prompt's token count tracks the
# repeat count closely on any BPE vocabulary, which is what makes the bracket
# tight without assuming a characters-per-token ratio.
_FILLER_TOKEN = " the"

# Room for the chat template, role markers and the single generated token. The
# under-probe sits this far below the configured window so ordinary scaffolding
# cannot push it over and produce a false "too small". Capped at a fraction of the
# window as well as an absolute size: a flat reserve is half of a 512-token window,
# which would leave the probe too far below to detect a half-sized server.
_SCAFFOLD_TOKENS = 256
_SCAFFOLD_FRACTION = 8
# A prompt so small that no configured window can reject it. If even this is refused
# the server is not answering, and the bracket below would read that as "the window is
# too small" — the same wrong verdict for a completely different cause.
_CANARY_TOKENS = 64
# The over-probe sits this far above, comfortably beyond any slop in the filler's
# tokenisation, so a rejection is unambiguous.
_OVERSHOOT = 4

# Optional refinement only. Never load-bearing: if it matches, the number is shown
# alongside the bracket; if it does not, the bracket still stands on its own.
_REPORTED = re.compile(
    r"(?:context (?:size|length|window)|available)\D{0,40}?\(?(\d{3,7})\s*tokens?\)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ContextReport:
    """Where the server's real window sits relative to the configured one."""

    agent: str
    configured: int
    accepts_under: bool
    rejects_over: bool
    reported: int | None = None
    # False when even a 64-token prompt was refused. The window was never measured:
    # the server was busy or unwell, and saying TOO SMALL would send someone to lower
    # a context that is fine.
    available: bool = True

    @property
    def measured(self) -> bool:
        """Whether the probe learned anything at all."""
        return self.available

    @property
    def agrees(self) -> bool:
        """True when the server's window is at least what the configuration promised.

        A server with *more* context is not a failure: the run stays inside its
        configured budget, so the guarantee still holds. A server with less is the
        failure, and it is the one that actually happened.
        """
        return self.accepts_under

    @property
    def inconclusive(self) -> bool:
        """A refusal that says nothing about the window."""
        return not self.available

    @property
    def larger_than_configured(self) -> bool:
        """Accepted a prompt well beyond the configured window."""
        return self.accepts_under and not self.rejects_over

    def describe(self) -> str:
        named = f", server names {self.reported:,}" if self.reported is not None else ""
        if not self.available:
            return (
                f"{self.agent}: refused even a {_CANARY_TOKENS}-token prompt, so its "
                "window was not measured — the server is busy or unwell, which a "
                "corpus run in progress is the usual cause of [UNMEASURED]"
            )
        if not self.accepts_under:
            return (
                f"{self.agent}: rejected a prompt of ~{self.under_tokens:,} tokens, "
                f"so its window is under the configured {self.configured:,}"
                f"{named} [TOO SMALL]"
            )
        if self.larger_than_configured:
            return (
                f"{self.agent}: accepted ~{self.over_tokens:,} tokens, so its window "
                f"exceeds the configured {self.configured:,} [ok, larger]"
            )
        return (
            f"{self.agent}: accepted ~{self.under_tokens:,} and rejected "
            f"~{self.over_tokens:,}, bracketing the configured {self.configured:,}"
            f"{named} [ok]"
        )

    @property
    def under_tokens(self) -> int:
        reserve = min(_SCAFFOLD_TOKENS, max(self.configured // _SCAFFOLD_FRACTION, 1))
        return max(self.configured - reserve, 1)

    @property
    def over_tokens(self) -> int:
        return self.configured * _OVERSHOOT


def parse_reported_context(body: str) -> int | None:
    """A context size named in a rejection body, if it names one.

    Presentation only. Nothing branches on this, because how a server phrases a
    rejection is that server's business.
    """
    match = _REPORTED.search(body)
    return int(match.group(1)) if match else None


def _accepts(provider: LLMProvider, model: ModelInfo, tokens: int) -> tuple[bool, str | None]:
    """Whether a prompt of roughly `tokens` is accepted, and any rejection body."""
    prompt = RenderedPrompt(
        template_name="context_probe",
        template_version="v2",
        template_sha256="0" * 64,
        messages=(Message(role="user", content=_FILLER_TOKEN * tokens),),
    )
    try:
        provider.complete(
            model=model,
            prompt=prompt,
            sampling=SamplingParams(temperature=0.0, max_tokens=1),
        )
    except ModelBudgetExhaustedError:
        # ACCEPTED. A reasoning model asked for one token emits reasoning and no
        # answer, which the provider reports as budget exhaustion — but reaching
        # generation at all proves the prompt fitted the window. Reading this as a
        # rejection made the probe report TOO SMALL for a server that was fine.
        return True, None
    except InferenceStatusError as error:
        return False, error.body
    except InferenceError:
        # A timeout or a dropped socket is not a verdict about the window, and
        # returning one would be worse than failing: it would read as TOO SMALL and
        # send someone to change a setting that was never wrong.
        raise
    return True, None


def probe_context(
    provider: LLMProvider, model: ModelInfo, *, agent: str, configured: int
) -> ContextReport:
    """Bracket the server's window against the configured one.

    Two requests, each generating a single token. The under-probe is the expensive
    one — the server must prefill it — but that is seconds, against nights.
    """
    report = ContextReport(
        agent=agent, configured=configured, accepts_under=False, rejects_over=True
    )
    # The canary first. A busy server rejects the under-probe exactly as a small
    # window does, and bracketing cannot tell them apart — so the two are separated
    # by asking a question no configured window can refuse. Without it a corpus run
    # in progress makes every agent read TOO SMALL, and the remedy that suggests is
    # to lower a context that was never the problem.
    accepted_canary, _ = _accepts(provider, model, _CANARY_TOKENS)
    if not accepted_canary:
        return ContextReport(
            agent=agent,
            configured=configured,
            accepts_under=False,
            rejects_over=True,
            available=False,
        )

    accepted_under, body = _accepts(provider, model, report.under_tokens)
    if not accepted_under:
        return ContextReport(
            agent=agent,
            configured=configured,
            accepts_under=False,
            rejects_over=True,
            reported=parse_reported_context(body) if body else None,
        )

    accepted_over, over_body = _accepts(provider, model, report.over_tokens)
    return ContextReport(
        agent=agent,
        configured=configured,
        accepts_under=True,
        rejects_over=not accepted_over,
        reported=parse_reported_context(over_body) if over_body else None,
    )
