"""Ask the server what its context actually is, rather than trusting the config.

The first corpus run failed because `config/default.toml` and the inference
server disagreed: one said what the run needed, the other was loaded at 8,192, and
nothing compared them. A pre-flight that checks a configured number against a computed number would
have passed that run happily — it would have been comparing two things that were
both true and neither of which was the server.

Context length is a *server-side* setting, in exactly the sense that KV-cache
quantisation is: invisible to the cache key, invisible to the model fingerprint,
and able to change what the model does without changing anything this repository
can see. So it is measured, the same way the grammar probe measures constrained
decoding instead of assuming the backend supports it.

The measurement is cheap because the server volunteers the answer. A deliberately
oversized request is rejected before any generation happens, and the rejection
names the real window:

    the request (13830 tokens) exceeds the available context size (8192 tokens)

One request per agent, a fraction of a second each, no tokens generated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mapf.core.errors import InferenceError, InferenceStatusError
from mapf.core.ports import LLMProvider, Message, ModelInfo, RenderedPrompt, SamplingParams

# The number in "available context size (8192 tokens)". Kept deliberately loose
# about wording, and anchored on the parenthesised figure that follows.
_REPORTED = re.compile(
    r"(?:context (?:size|length|window)|available)\D{0,40}?\(?(\d{3,7})\s*tokens?\)?",
    re.IGNORECASE,
)
_OVERSIZE_FACTOR = 2
# One token is roughly four characters of this filler; the exact ratio does not
# matter because the request only has to be comfortably too large.
_CHARS_PER_TOKEN = 4
_PROBE_WORD = "reconciliation "


@dataclass(frozen=True)
class ContextReport:
    """What the server said, next to what the configuration claimed."""

    agent: str
    configured: int
    reported: int | None
    accepted_oversize: bool

    @property
    def agrees(self) -> bool:
        """True when the server's real window is at least what config promised.

        A server with *more* context than configured is not a failure: the run
        stays inside the configured budget, so the guarantee still holds. A server
        with less is the failure, and it is the one that actually happened.
        """
        if self.accepted_oversize:
            return True
        if self.reported is None:
            return False
        return self.reported >= self.configured

    def describe(self) -> str:
        if self.accepted_oversize:
            return f"{self.agent}: server accepted {self.configured * _OVERSIZE_FACTOR:,} tokens"
        if self.reported is None:
            return f"{self.agent}: server rejected the probe without naming its context"
        verdict = "ok" if self.agrees else "TOO SMALL"
        return (
            f"{self.agent}: configured {self.configured:,}, "
            f"server reports {self.reported:,} [{verdict}]"
        )


def parse_reported_context(body: str) -> int | None:
    """The context size named in a rejection body, if it names one."""
    match = _REPORTED.search(body)
    return int(match.group(1)) if match else None


def probe_context(
    provider: LLMProvider, model: ModelInfo, *, agent: str, configured: int
) -> ContextReport:
    """Send one deliberately oversized request and read the server's answer.

    `max_tokens=1` so that if the server *does* accept it, the cost is a single
    token rather than a full generation. Acceptance is itself informative: the
    window is at least as large as the probe.
    """
    filler = _PROBE_WORD * (
        configured * _OVERSIZE_FACTOR * _CHARS_PER_TOKEN // len(_PROBE_WORD)
    )
    prompt = RenderedPrompt(
        template_name="context_probe",
        template_version="v1",
        template_sha256="0" * 64,
        messages=(Message(role="user", content=filler),),
    )
    try:
        provider.complete(
            model=model, prompt=prompt, sampling=SamplingParams(temperature=0.0, max_tokens=1)
        )
    except InferenceStatusError as error:
        return ContextReport(
            agent=agent,
            configured=configured,
            reported=parse_reported_context(error.body),
            accepted_oversize=False,
        )
    except InferenceError:
        # A timeout or a dropped socket says nothing about the window, and
        # inventing a verdict from it would be worse than reporting none.
        return ContextReport(
            agent=agent, configured=configured, reported=None, accepted_oversize=False
        )
    return ContextReport(
        agent=agent, configured=configured, reported=None, accepted_oversize=True
    )
