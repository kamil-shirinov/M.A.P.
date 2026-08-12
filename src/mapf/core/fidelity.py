"""Transcription fidelity — is the v2 architecture doing what it claims?

v2's premise is that Agent 2 produces magnitudes and Agent 3 transcribes them.
That is an architectural claim, and until it is measured it is only a claim. This
turns it into a number by extracting what the analyst actually stated and
comparing it against what the structuralist actually emitted.

**Two failure modes, recorded separately, because they blame different agents:**

- `unparseable` — the analyst did not emit the required line. Agent 2
  non-compliance. Nothing to transcribe, so fidelity is undefined, not zero.
- `divergent` — the analyst stated a number and Agent 3 emitted a different one.
  Agent 3 infidelity.

Collapsing them into one signal would hide which agent is at fault, and they have
opposite remedies: one is a prompt problem in Agent 2, the other in Agent 3.

Both are warnings. Neither rejects a forecast — a model that reasons well and
formats badly still produced a forecast, and refusing it would trade a real output
for a tidy metric.

The line is strictly formatted on purpose. Scraping prose for "a moderate upward
move" is what produced the first live run's failure; a fidelity check that
quietly fails to parse is worse than no check, because it reports a clean sheet.
"""

from __future__ import annotations

import re

from mapf.core.models import DomainModel, ScenarioSet

BRANCHES = ("bullish", "base_case", "bearish")

# One line per scenario, self-labelling and order-independent. Decimals are
# mandatory: `return=+5` is the percentage-point error this whole migration was
# about, and it must fail to parse rather than be silently accepted as 500%.
ESTIMATE_LINE = re.compile(
    r"^[ \t]*ESTIMATE[ \t]+(bullish|base_case|bearish)"
    r"[ \t]+weight=(\d+\.\d+)"
    r"[ \t]+return=([+-]?\d+\.\d+)"
    r"[ \t]+vol=(\d+\.\d+)[ \t]*$",
    re.MULTILINE,
)

TOLERANCE = 1e-6


class StatedEstimate(DomainModel):
    """What the analyst committed to, before anyone structured it."""

    weight: float
    price_return: float
    annualised_vol: float


class TranscriptionFidelity(DomainModel):
    parsed: tuple[str, ...] = ()
    unparseable: tuple[str, ...] = ()
    divergent: tuple[str, ...] = ()
    max_return_divergence: float = 0.0

    @property
    def analyst_compliance(self) -> float:
        """Fraction of scenarios for which Agent 2 emitted a usable line."""
        return len(self.parsed) / len(BRANCHES)

    @property
    def fidelity(self) -> float | None:
        """Of the scenarios Agent 2 stated, the fraction Agent 3 carried across.

        `None` when nothing parsed — undefined, not zero. Reporting 0.0 there would
        blame Agent 3 for Agent 2's silence.
        """
        if not self.parsed:
            return None
        return (len(self.parsed) - len(self.divergent)) / len(self.parsed)

    @property
    def any_flag(self) -> bool:
        return bool(self.unparseable or self.divergent)


def parse_estimates(narrative: str) -> dict[str, StatedEstimate]:
    """Extract every well-formed ESTIMATE line. First wins on duplicates."""
    found: dict[str, StatedEstimate] = {}
    for match in ESTIMATE_LINE.finditer(narrative):
        branch, weight, price_return, vol = match.groups()
        if branch in found:
            continue
        found[branch] = StatedEstimate(
            weight=float(weight),
            price_return=float(price_return),
            annualised_vol=float(vol),
        )
    return found


def measure(narrative: str, scenarios: ScenarioSet) -> TranscriptionFidelity:
    stated = parse_estimates(narrative)
    parsed: list[str] = []
    unparseable: list[str] = []
    divergent: list[str] = []
    worst = 0.0

    for branch in BRANCHES:
        estimate = stated.get(branch)
        if estimate is None:
            unparseable.append(branch)
            continue
        parsed.append(branch)
        emitted = getattr(scenarios, branch)
        gap = abs(emitted.price_return - estimate.price_return)
        worst = max(worst, gap)
        if (
            gap > TOLERANCE
            or abs(emitted.annualised_vol - estimate.annualised_vol) > TOLERANCE
            or abs(emitted.probability_weight - estimate.weight) > TOLERANCE
        ):
            divergent.append(branch)

    return TranscriptionFidelity(
        parsed=tuple(parsed),
        unparseable=tuple(unparseable),
        divergent=tuple(divergent),
        max_return_divergence=worst,
    )
