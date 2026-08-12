"""Transcription fidelity, and the parser it rests on.

A fidelity check that silently fails to parse is worse than none: it reports a
clean sheet for a run nobody measured. So the parser is tested against malformed
input at least as hard as against valid input.
"""

from __future__ import annotations

import pytest

from mapf.core.fidelity import (
    TranscriptionFidelity,
    measure,
    parse_estimates,
)
from tests.conftest import make_scenario_set

GOOD = """**Bullish**
Reasoning goes here.
ESTIMATE bullish weight=0.30 return=+0.06 vol=0.28

**Base case**
More reasoning.
ESTIMATE base_case weight=0.50 return=+0.005 vol=0.20

**Bearish**
Yet more.
ESTIMATE bearish weight=0.20 return=-0.075 vol=0.35
"""


# ---------------------------------------------------------------------------
# Parser — valid
# ---------------------------------------------------------------------------
def test_all_three_estimates_parse() -> None:
    stated = parse_estimates(GOOD)
    assert set(stated) == {"bullish", "base_case", "bearish"}
    assert stated["bullish"].price_return == pytest.approx(0.06)
    assert stated["bearish"].annualised_vol == pytest.approx(0.35)
    assert stated["base_case"].weight == pytest.approx(0.50)


def test_order_does_not_matter() -> None:
    """Self-labelling lines, so a model that reorders its sections still parses."""
    reordered = "\n".join(reversed(GOOD.splitlines()))
    assert set(parse_estimates(reordered)) == {"bullish", "base_case", "bearish"}


def test_leading_whitespace_is_tolerated() -> None:
    assert parse_estimates("   ESTIMATE bullish weight=0.30 return=+0.06 vol=0.28")


def test_an_unsigned_return_is_accepted() -> None:
    """`return=0.00` for a flat case is natural; demanding a sign would fail it."""
    stated = parse_estimates("ESTIMATE base_case weight=0.50 return=0.00 vol=0.20")
    assert stated["base_case"].price_return == pytest.approx(0.0)


def test_the_first_line_wins_on_duplicates() -> None:
    text = (
        "ESTIMATE bullish weight=0.30 return=+0.06 vol=0.28\n"
        "ESTIMATE bullish weight=0.40 return=+0.09 vol=0.30\n"
    )
    assert parse_estimates(text)["bullish"].price_return == pytest.approx(0.06)


# ---------------------------------------------------------------------------
# Parser — malformed. Each of these MUST fail to parse.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "line",
    [
        "ESTIMATE bullish weight=0.30 return=+6 vol=0.28",  # integer return
        "ESTIMATE bullish weight=0.30 return=+0.06% vol=0.28",  # percent sign
        "ESTIMATE bullish weight=0.30 return=+6% vol=0.28",  # both
        "ESTIMATE bull weight=0.30 return=+0.06 vol=0.28",  # wrong branch name
        "ESTIMATE base case weight=0.30 return=+0.06 vol=0.28",  # space, not underscore
        "ESTIMATE bullish weight=0.30 vol=0.28",  # missing return
        "ESTIMATE bullish return=+0.06 vol=0.28",  # missing weight
        "ESTIMATE bullish weight=0.30 return=+0.06",  # missing vol
        "estimate bullish weight=0.30 return=+0.06 vol=0.28",  # lowercase keyword
        "ESTIMATE bullish weight=30 return=+0.06 vol=0.28",  # integer weight
        "The ESTIMATE bullish weight=0.30 return=+0.06 vol=0.28",  # embedded in prose
        "Return: +0.06 Vol: 0.28",  # the older prose form
        "The price could see a moderate upward move.",  # v1's actual output
    ],
    ids=[
        "integer-return",
        "percent-sign",
        "integer-and-percent",
        "wrong-branch",
        "space-not-underscore",
        "no-return",
        "no-weight",
        "no-vol",
        "lowercase",
        "integer-weight",
        "embedded-in-prose",
        "older-prose-form",
        "v1-actual-output",
    ],
)
def test_malformed_lines_do_not_parse(line: str) -> None:
    assert parse_estimates(line) == {}


def test_an_integer_return_must_fail_rather_than_be_accepted() -> None:
    """`return=+5` is the percentage-point error the whole migration was about.
    Read as a fraction it is 500%. It must not parse."""
    assert parse_estimates("ESTIMATE bullish weight=0.30 return=+5 vol=0.28") == {}


# ---------------------------------------------------------------------------
# The two failure modes, kept apart
# ---------------------------------------------------------------------------
def test_a_faithful_transcription_scores_one() -> None:
    scenarios = make_scenario_set(
        weights=(0.30, 0.50, 0.20), modifiers=(0.06, 0.005, -0.075), vols=(0.28, 0.20, 0.35)
    )
    result = measure(GOOD, scenarios)
    assert result.parsed == ("bullish", "base_case", "bearish")
    assert result.divergent == ()
    assert result.fidelity == 1.0
    assert result.analyst_compliance == 1.0
    assert result.any_flag is False


def test_agent_3_infidelity_is_divergence_not_non_compliance() -> None:
    """The analyst stated a number and Agent 3 emitted a different one."""
    scenarios = make_scenario_set(
        weights=(0.30, 0.50, 0.20), modifiers=(0.01, 0.005, -0.075), vols=(0.28, 0.20, 0.35)
    )
    result = measure(GOOD, scenarios)
    assert result.divergent == ("bullish",)
    assert result.unparseable == ()
    assert result.fidelity == pytest.approx(2 / 3)
    assert result.max_return_divergence == pytest.approx(0.05)


def test_agent_2_non_compliance_is_unparseable_not_divergence() -> None:
    """v1's failure mode: no numbers at all. Blaming Agent 3 would be wrong."""
    prose = "The price could see a moderate upward move with moderate turbulence."
    result = measure(prose, make_scenario_set())
    assert result.unparseable == ("bullish", "base_case", "bearish")
    assert result.divergent == ()
    assert result.analyst_compliance == 0.0


def test_fidelity_is_undefined_not_zero_when_nothing_parsed() -> None:
    """Reporting 0.0 there would blame Agent 3 for Agent 2's silence."""
    assert measure("no estimates here", make_scenario_set()).fidelity is None


def test_the_two_modes_can_co_occur_and_stay_separate() -> None:
    partial = "ESTIMATE bullish weight=0.30 return=+0.06 vol=0.28"
    scenarios = make_scenario_set(
        weights=(0.30, 0.50, 0.20), modifiers=(0.09, 0.005, -0.075), vols=(0.28, 0.20, 0.35)
    )
    result = measure(partial, scenarios)
    assert result.parsed == ("bullish",)
    assert result.unparseable == ("base_case", "bearish")
    assert result.divergent == ("bullish",)
    assert result.fidelity == 0.0
    assert result.analyst_compliance == pytest.approx(1 / 3)


def test_a_divergent_volatility_counts_even_when_the_return_matches() -> None:
    scenarios = make_scenario_set(
        weights=(0.30, 0.50, 0.20), modifiers=(0.06, 0.005, -0.075), vols=(0.99, 0.20, 0.35)
    )
    assert measure(GOOD, scenarios).divergent == ("bullish",)


def test_an_empty_result_is_clean() -> None:
    assert TranscriptionFidelity().any_flag is False
    assert TranscriptionFidelity().fidelity is None
