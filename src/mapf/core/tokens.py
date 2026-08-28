"""Estimating how many tokens a document will cost, and against which ceiling.

This exists because nothing ever measured document size against context capacity,
and the first corpus run discovered the mismatch an hour in, on roughly half the
corpus. It is a pre-flight question, not a runtime one.

**The estimate is deliberately pessimistic.** It feeds a refusal gate, and the two
errors are not symmetric: over-estimating costs a needless truncation warning,
under-estimating costs a night. The ratio is calibrated against real rejections
from the halted run rather than assumed —

    ALLY  51,188 chars reported 13,830 tokens  ->  3.70 chars/token
    FCX  131,879 chars reported ~33,000 tokens ->  4.00 chars/token
    TEL   29,216 chars fitted inside 8,192; FAST 32,295 did not

— and the gate uses the low end of that range, because financial prose tokenises
worse than ordinary English: figures, tickers and table punctuation all split into
more tokens per character than words do.
"""

from __future__ import annotations

from dataclasses import dataclass

# Low end of the measured range. Fewer chars per token means more tokens, which is
# the conservative direction for a gate that must not let a doomed item through.
CHARS_PER_TOKEN = 3.5

# Everything in an agent's window that is not the document: the rendered template,
# the quarantine delimiters, the chat scaffolding.
TEMPLATE_RESERVE = 800


def estimate_tokens(text: str | int) -> int:
    """Tokens for a string, or for a character count already known."""
    chars = text if isinstance(text, int) else len(text)
    return int(chars / CHARS_PER_TOKEN) + 1


@dataclass(frozen=True)
class AgentBudget:
    """One agent's room for a document, after everything else it must hold."""

    agent: str
    context_tokens: int
    max_tokens: int | None

    @property
    def output_reserve(self) -> int:
        """Room kept for generation.

        Generation shares the window with the prompt. Where `max_tokens` is set the
        whole budget must fit, because a run that spent it would otherwise die at
        the context ceiling — the TSLA failure.
        """
        return self.max_tokens if self.max_tokens is not None else 2000

    @property
    def document_budget(self) -> int:
        return self.context_tokens - TEMPLATE_RESERVE - self.output_reserve


@dataclass(frozen=True)
class FitResult:
    """Whether one document fits every agent that will see it."""

    tokens: int
    binding_agent: str
    headroom: int

    @property
    def fits(self) -> bool:
        return self.headroom >= 0


def check_fit(document_tokens: int, budgets: list[AgentBudget]) -> FitResult:
    """The tightest agent, and by how much the document clears or misses it.

    Only agents that actually see the document are passed in. The analyst reads the
    intake's compressed facts and the structuralist reads the analyst's narrative,
    so a long exhibit binds on intake alone — reporting the binding agent is what
    turns "it will not fit" into "raise this one number".
    """
    if not budgets:
        raise ValueError("no agent budgets supplied")
    tightest = min(budgets, key=lambda b: b.document_budget)
    return FitResult(
        tokens=document_tokens,
        binding_agent=tightest.agent,
        headroom=tightest.document_budget - document_tokens,
    )


# Measured from real runs rather than assumed: the analyst's rendered template runs
# to 1,229 tokens and the structuralist's to 464, so these are those maxima with
# margin. They are the part of an agent's window that its own prompt scaffolding
# occupies before any upstream payload arrives.
PROMPT_OVERHEAD: dict[str, int] = {
    "intake": 800,
    "analyst": 1_536,
    "structuralist": 768,
}

# Generation room for an agent that declares no `max_tokens`; the server's own
# default is invisible here, so a reserve is assumed rather than pretended away.
DEFAULT_GENERATION_RESERVE = 2_000


def generation_reserve(max_tokens: int | None) -> int:
    return max_tokens if max_tokens is not None else DEFAULT_GENERATION_RESERVE


def prompt_allowance(context_tokens: int, max_tokens: int | None) -> int:
    """How large a prompt this agent can accept.

    Generation shares the window with the prompt, so the allowance is the window
    less whatever generation may consume.
    """
    return context_tokens - generation_reserve(max_tokens)
