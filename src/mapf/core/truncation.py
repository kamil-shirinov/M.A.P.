"""The head-and-tail truncation rule (ADR 0020).

Eleven of the 709 frozen exhibits exceed a 32,768-token context. They belong to
three tickers, and rather than raise the context to a size that does not fit in
memory, those documents are cut to a fixed shape.

**The parameters are constants, not arguments with defaults.** A truncation length
that can be passed in is a truncation length someone tunes after seeing a result,
which turns a preprocessing step into a researcher degree of freedom. They live in
ADR 0020 and here, and nowhere else.

**The invariant is enforced, not trusted.** The token estimate carries real
uncertainty — the observed ratio ranges 3.5 to 4.0 characters per token — so
cutting to a character count derived from an estimate could still overflow if the
true ratio were worse than assumed. Instead the result is re-estimated and cut
again until it is genuinely under budget. Ratio error can then cost a slightly
shorter document, never a run-time failure.

**The source hash is not affected.** `Document.id` hashes the bytes as they arrived
(ADR 0005), so it keeps meaning "this is what EDGAR served". Truncation is a
processing step recorded alongside it, never folded into it.
"""

from __future__ import annotations

from dataclasses import dataclass

from mapf.core.models import UntrustedText
from mapf.core.tokens import CHARS_PER_TOKEN, estimate_tokens

# ADR 0020. Fixed here so they cannot become a tuned parameter.
HEAD_TOKENS = 24_000
TAIL_TOKENS = 4_000

# The name that appears INSIDE the document, in the elision marker. Deliberately
# bare: it is text the model reads, and changing it would change the input to every
# truncated item for no reason a forecast could notice.
RULE = "head_tail_v1"


def rule_id() -> str:
    """The identifier the RECORD carries: the rule and the parameters it ran with.

    `head_tail_v1` was the same string at 3.5 characters per token and at 3.0, which
    cut the same documents to 98,121 and 84,121 characters — **the identifier did not
    change when its parameter did**, so two incompatible bases were labelled
    identically and a corpus could mix them while every record agreed.

    A version suffix would not have helped: the point is not that someone forgot to
    bump it, but that a name maintained by hand can disagree with the parameters it
    names. This one is computed from them, so it cannot.
    """
    return f"{RULE}(head={HEAD_TOKENS},tail={TAIL_TOKENS},ratio={CHARS_PER_TOKEN})"


# Each shrink step cuts head and tail together by this much, preserving the 6:1
# shape rather than eroding the head alone — at a small budget the fixed tail can
# exceed it by itself, and a head-only shrink would never converge.
_SHRINK = 0.9
_MIN_HEAD_CHARS = 2_000
_MIN_TAIL_CHARS = 200


@dataclass(frozen=True)
class Truncation:
    """What was done to one document, and whether anything was done at all."""

    rule: str
    applied: bool
    original_chars: int
    kept_chars: int
    head_chars: int
    tail_chars: int
    estimated_tokens: int

    @property
    def removed_chars(self) -> int:
        """Source characters dropped.

        Deliberately not `original - kept`: `kept` includes the elision marker,
        which is text this rule *added*. Counting it would make the record disagree
        with the number the marker itself states.
        """
        return max(self.original_chars - self.head_chars - self.tail_chars, 0)

    def describe(self) -> str:
        if not self.applied:
            return f"{self.rule}: not applied ({self.original_chars:,} chars fit)"
        return (
            f"{self.rule}: {self.original_chars:,} -> {self.kept_chars:,} chars "
            f"({self.removed_chars:,} elided), ~{self.estimated_tokens:,} tokens"
        )


def _marker(removed: int, head: int, tail: int) -> str:
    return (
        f"\n\n[... {removed:,} characters elided by {RULE}: kept the first "
        f"{head:,} and last {tail:,} characters of this exhibit ...]\n\n"
    )


def plan_truncation(original_chars: int, *, budget_tokens: int) -> Truncation:
    """What the rule would do to a document of this size, without needing the text.

    The pre-flight gate knows only character counts from the frozen record, and
    fabricating a placeholder document to measure would both waste memory and put
    an `UntrustedText` construction somewhere it has no business being.
    """
    if estimate_tokens(original_chars) <= budget_tokens:
        return Truncation(
            rule=RULE,
            applied=False,
            original_chars=original_chars,
            kept_chars=original_chars,
            head_chars=original_chars,
            tail_chars=0,
            estimated_tokens=estimate_tokens(original_chars),
        )

    head_chars = min(int(HEAD_TOKENS * CHARS_PER_TOKEN), original_chars)
    tail_chars = min(int(TAIL_TOKENS * CHARS_PER_TOKEN), max(original_chars - head_chars, 0))
    while True:
        marker = len(_marker(original_chars - head_chars - tail_chars, head_chars, tail_chars))
        kept = head_chars + tail_chars + marker
        tokens = estimate_tokens(kept)
        at_floor = head_chars <= _MIN_HEAD_CHARS and tail_chars <= _MIN_TAIL_CHARS
        if tokens <= budget_tokens or at_floor:
            break
        head_chars = max(int(head_chars * _SHRINK), _MIN_HEAD_CHARS)
        tail_chars = max(int(tail_chars * _SHRINK), _MIN_TAIL_CHARS)
    return Truncation(
        rule=RULE,
        applied=True,
        original_chars=original_chars,
        kept_chars=kept,
        head_chars=head_chars,
        tail_chars=tail_chars,
        estimated_tokens=tokens,
    )


def truncate(text: UntrustedText, *, budget_tokens: int) -> tuple[UntrustedText, Truncation]:
    """Cut a document to head-and-tail if it exceeds `budget_tokens`.

    Returns the text unchanged when it already fits, so the rule is a no-op for the
    698 exhibits that need nothing — applied uniformly, biting only where it must.

    Takes and returns `UntrustedText` so taint propagates *through* the
    transformation. Returning a bare `str` would push re-labelling onto every
    caller, and a caller that forgot would silently launder filed text into
    trusted text (ADR 0005).
    """
    original = len(text)
    if estimate_tokens(original) <= budget_tokens:
        return text, Truncation(
            rule=RULE,
            applied=False,
            original_chars=original,
            kept_chars=original,
            head_chars=original,
            tail_chars=0,
            estimated_tokens=estimate_tokens(original),
        )

    head_chars = int(HEAD_TOKENS * CHARS_PER_TOKEN)
    tail_chars = int(TAIL_TOKENS * CHARS_PER_TOKEN)

    # The invariant: re-estimate and cut again rather than trusting the ratio.
    # Estimating at 3.5 against a true 3.0 would otherwise overflow at run time,
    # which is precisely the failure this rule exists to prevent.
    while True:
        head, tail = text[:head_chars], text[-tail_chars:] if tail_chars else ""
        candidate = head + _marker(original - len(head) - len(tail), len(head), len(tail)) + tail
        tokens = estimate_tokens(candidate)
        at_floor = head_chars <= _MIN_HEAD_CHARS and tail_chars <= _MIN_TAIL_CHARS
        if tokens <= budget_tokens or at_floor:
            break
        head_chars = max(int(head_chars * _SHRINK), _MIN_HEAD_CHARS)
        tail_chars = max(int(tail_chars * _SHRINK), _MIN_TAIL_CHARS)

    return UntrustedText(candidate), Truncation(
        rule=RULE,
        applied=True,
        original_chars=original,
        kept_chars=len(candidate),
        head_chars=len(head),
        tail_chars=len(tail),
        estimated_tokens=tokens,
    )
