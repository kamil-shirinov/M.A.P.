"""Soft quality checks on a finished forecast.

**Warnings, never rejections.** Both conditions below can be entirely legitimate,
and a validator that refused them would suppress real forecasts to catch
occasional bad ones. What they must not do is pass *silently* — the first live run
produced a degenerate spread and a fabricated figure, and nothing anywhere said so.

Recorded in the manifest so Phase 2 can filter on them rather than rediscovering
them one forecast at a time.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from math import sqrt

from mapf.core.models import DomainModel, ScenarioSet

# 0.5% scaled by sqrt(time), because that is how price dispersion actually grows.
# A flat number would be far too tight at one day and far too loose at a year.
# The coefficient is a judgement, not a result — it is set so that a 21-day spread
# below about 2.3% trips, which is roughly a tenth of AAPL's typical range over
# that window.
SPREAD_FLOOR_COEFFICIENT = 0.005

_NUMERAL = re.compile(r"-?\d+(?:\.\d+)?")

# Numbers this small are almost always ordinals, counts or years rather than
# claims about the company, and flagging them would bury the signal.
_IGNORED_NUMERALS = frozenset({0.0, 1.0, 2.0, 3.0})


class QualityFlags(DomainModel):
    """What was odd about this forecast. Empty is the normal case."""

    degenerate_spread: bool = False
    spread: float = 0.0
    spread_floor: float = 0.0
    ungrounded_numerals: tuple[str, ...] = ()

    @property
    def any_flag(self) -> bool:
        return self.degenerate_spread or bool(self.ungrounded_numerals)


def spread_floor(horizon_days: int) -> float:
    return SPREAD_FLOOR_COEFFICIENT * sqrt(horizon_days)


def _numerals(text: str) -> set[float]:
    values: set[float] = set()
    for token in _NUMERAL.findall(text):
        try:
            value = float(token)
        except ValueError:  # pragma: no cover - the regex cannot produce this
            continue
        if abs(value) not in _IGNORED_NUMERALS:
            values.add(abs(value))
    return values


def check(scenarios: ScenarioSet, *, horizon_days: int, facts: Iterable[str]) -> QualityFlags:
    """Both soft checks in one pass.

    **Degenerate spread.** Three scenarios landing within a hair of each other are
    not three scenarios. A genuinely flat outlook is legitimate — hence a warning —
    but the run should say so rather than presenting three near-identical numbers
    as a distribution of views.

    **Ungrounded numerals.** Every figure in a justification should trace back to a
    material fact. This is deliberately crude and its recall is not high: models
    paraphrase, round, and compute. It would not catch "just over 46%" written for
    46.3%. It *would* have caught the 66.3% gross margin the first live run
    invented where the source said 46.3% — and converting an invisible failure into
    a visible one is worth a check that is only sometimes right.

    False positives are expected and cost nothing but a line in the manifest.
    """
    bull = scenarios.bullish.price_return
    bear = scenarios.bearish.price_return
    spread = bull - bear
    floor = spread_floor(horizon_days)

    grounded = set()
    for fact in facts:
        grounded |= _numerals(fact)

    ungrounded: list[str] = []
    for name in ("bullish", "base_case", "bearish"):
        scenario = getattr(scenarios, name)
        for value in sorted(_numerals(scenario.justification)):
            # 1% relative, or 0.05 absolute for small numbers. Models round: a
            # justification saying "about 46%" for a fact of 46.3% is honest
            # paraphrase, and flagging it would bury the signal under noise.
            if not any(abs(value - known) <= max(0.05, 0.01 * known) for known in grounded):
                ungrounded.append(f"{name}: {value:g}")

    return QualityFlags(
        degenerate_spread=spread < floor,
        spread=spread,
        spread_floor=floor,
        ungrounded_numerals=tuple(ungrounded),
    )
