"""Measuring where a model's knowledge stops.

Published cutoffs are unavailable for two of the three models here and unreliable
in general, and the corpus split depends on the answer — so it is measured.

**Two methods with unrelated failure modes, and neither is the backbone.**

- `hedge_rate` asks about a month and classifies whether the model answers or
  declines. Needs no ground truth at all, so it cannot be corrupted by the item
  author's own recall. Its failure mode is conflating "after my cutoff" with
  "unfamiliar" — a model may hedge about a quiet month it does know.
- `recall_accuracy` asks yes/no questions about corporate events dated by EDGAR.
  Authoritative and verifiable. Its failure mode is measuring **obscurity** rather
  than recency — a model may not know a mid-cap's affairs at any date, which
  flattens the curve and reads as "no knowledge anywhere".

Agreement between two methods whose failure modes are unrelated is far stronger
evidence than either alone. **Disagreement is itself a finding**: it means the
boundary is soft, and a soft boundary becomes a third corpus category rather than
being forced to one side (the ADR 0013 rule — an unknown must never read as clean).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

# Phrases a model reaches for when asked past its knowledge. Deliberately
# conservative: a false positive here reads as "cutoff earlier than it is", which
# would shrink the post-cutoff corpus rather than contaminate it.
HEDGE_PATTERNS: tuple[str, ...] = (
    r"\bi (?:do not|don't) have\b",
    r"\bmy (?:training|knowledge)\b",
    r"\blast update\b",
    r"\bknowledge cut[- ]?off\b",
    r"\bcut[- ]?off date\b",
    r"\bno information\b",
    r"\bnot able to (?:provide|access)\b",
    r"\bunable to (?:provide|access|confirm)\b",
    r"\bbeyond my\b",
    r"\bas of my\b",
    r"\bi cannot (?:provide|confirm|verify)\b",
    r"\bdata only (?:goes|extends)\b",
)

_HEDGE = re.compile("|".join(HEDGE_PATTERNS), re.IGNORECASE)
_YES = re.compile(r"\byes\b", re.IGNORECASE)
_NO = re.compile(r"\bno\b", re.IGNORECASE)


@dataclass(frozen=True)
class EventItem:
    """A yes/no question whose answer EDGAR settles.

    `true_answer` is False for a deliberately wrong month — without those the
    accuracy curve measures willingness to say yes, not knowledge.
    """

    company: str
    cik: int
    event: str
    month: date
    true_answer: bool
    accession: str | None = None


@dataclass(frozen=True)
class MonthResult:
    month: date
    hedge_rate: float
    accuracy: float | None
    answered: int
    total: int


def is_hedge(response: str) -> bool:
    """Did the model decline rather than answer?

    Checked before the yes/no parse, because "I don't have information after my
    training cutoff, but generally no" is a hedge that contains the word "no".
    """
    return bool(_HEDGE.search(response))


def parse_yes_no(response: str) -> bool | None:
    """Extract a verdict, or None when the model hedged or was ambiguous."""
    if is_hedge(response):
        return None
    head = response.strip()[:400]
    saw_yes, saw_no = bool(_YES.search(head)), bool(_NO.search(head))
    if saw_yes == saw_no:  # both or neither — no verdict
        return None
    return saw_yes


def summarise(
    month: date, hedges: list[bool], verdicts: list[tuple[bool | None, bool]]
) -> MonthResult:
    """Collapse one month's responses into the two curves.

    Accuracy is computed over *answered* items only. Scoring an unanswered item as
    wrong would fold the hedge signal into the accuracy signal and destroy the
    independence that makes the two methods worth running together.
    """
    answered = [(got, want) for got, want in verdicts if got is not None]
    accuracy = sum(1 for got, want in answered if got == want) / len(answered) if answered else None
    return MonthResult(
        month=month,
        hedge_rate=sum(hedges) / len(hedges) if hedges else 0.0,
        accuracy=accuracy,
        answered=len(answered),
        total=len(verdicts),
    )


def estimate_boundary(
    results: list[MonthResult], *, hedge_threshold: float = 0.5
) -> tuple[date | None, date | None]:
    """First month where hedging takes over, and where accuracy collapses to chance.

    Two independent estimates, deliberately not reconciled here. A caller that
    averaged them would be hiding exactly the disagreement that tells us the
    boundary is soft.
    """
    ordered = sorted(results, key=lambda r: r.month)
    hedge_month = next((r.month for r in ordered if r.hedge_rate >= hedge_threshold), None)
    accuracy_month = next(
        (r.month for r in ordered if r.accuracy is not None and r.accuracy <= 0.55), None
    )
    return hedge_month, accuracy_month
