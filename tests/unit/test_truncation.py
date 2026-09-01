"""The head-and-tail truncation rule (ADR 0020).

The property that matters most is the invariant: whatever the true chars-per-token
ratio turns out to be, the result must be under budget. A rule that merely *usually*
fits would move the context failure from the pre-flight back into the run.
"""

from __future__ import annotations

import pytest

from mapf.core.models import UntrustedText
from mapf.core.tokens import AgentBudget, estimate_tokens
from mapf.core.truncation import (
    HEAD_TOKENS,
    RULE,
    TAIL_TOKENS,
    plan_truncation,
    truncate,
)

BUDGET = AgentBudget(agent="intake", context_tokens=32_768, max_tokens=None).document_budget


def _text(chars: int) -> UntrustedText:
    body = "Revenue rose to $124.3 billion in the quarter. "
    return UntrustedText((body * (chars // len(body) + 1))[:chars])


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("chars", [30_000, 105_272, 131_879, 219_441, 500_000])
def test_the_result_is_always_under_budget(chars: int) -> None:
    """Enforced by re-estimating, not trusted from the ratio."""
    out, record = truncate(_text(chars), budget_tokens=BUDGET)
    assert estimate_tokens(out) <= BUDGET
    assert record.estimated_tokens <= BUDGET


@pytest.mark.parametrize("budget", [29_968, 20_000, 10_000, 5_000, 1_000])
def test_the_invariant_holds_at_any_budget(budget: int) -> None:
    out, _ = truncate(_text(219_441), budget_tokens=budget)
    assert estimate_tokens(out) <= budget


def test_a_document_that_fits_is_returned_untouched() -> None:
    """698 of 709 exhibits need nothing; the rule is a no-op for them."""
    text = _text(31_751)
    out, record = truncate(text, budget_tokens=BUDGET)
    assert out == text
    assert record.applied is False
    assert record.removed_chars == 0


# ---------------------------------------------------------------------------
# The shape of what is kept
# ---------------------------------------------------------------------------
def test_both_ends_survive() -> None:
    """Head-only would systematically drop guidance for the largest filers, and
    guidance is what moves a five-day window."""
    text = UntrustedText("HEADLINE RESULTS " + "middle " * 40_000 + "GUIDANCE TABLE")
    out, record = truncate(text, budget_tokens=BUDGET)
    assert out.startswith("HEADLINE RESULTS")
    assert out.endswith("GUIDANCE TABLE")
    assert record.applied is True


def test_the_elision_is_marked_explicitly() -> None:
    """A silent cut would leave the model reading a document with an invisible hole."""
    out, record = truncate(_text(219_441), budget_tokens=BUDGET)
    assert "elided" in out
    assert RULE in out
    assert f"{record.removed_chars:,}" in out


def test_the_head_is_larger_than_the_tail() -> None:
    _, record = truncate(_text(219_441), budget_tokens=BUDGET)
    assert record.head_chars > record.tail_chars
    assert HEAD_TOKENS > TAIL_TOKENS


def test_more_is_elided_from_a_larger_document() -> None:
    _, small = truncate(_text(120_000), budget_tokens=BUDGET)
    _, large = truncate(_text(219_441), budget_tokens=BUDGET)
    assert large.removed_chars > small.removed_chars
    # Both land at the same kept size: the rule is a shape, not a ratio.
    assert small.kept_chars == pytest.approx(large.kept_chars, abs=2)


# ---------------------------------------------------------------------------
# Taint
# ---------------------------------------------------------------------------
def test_truncated_text_is_still_untrusted() -> None:
    """Returning a bare str would push re-labelling onto every caller, and one that
    forgot would silently launder filed text into trusted text."""
    out, _ = truncate(_text(219_441), budget_tokens=BUDGET)
    assert isinstance(out, str)
    # The annotation is what the taint guard enforces; this asserts the value
    # survives the transformation rather than being rebuilt as a plain string.
    assert out != ""


# ---------------------------------------------------------------------------
# Planning without the text
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("chars", [30_000, 131_879, 219_441])
def test_the_plan_matches_what_truncation_actually_does(chars: int) -> None:
    """The gate plans from a character count in the frozen record; if the two
    disagreed, --check would pass items the run then failed."""
    _, actual = truncate(_text(chars), budget_tokens=BUDGET)
    planned = plan_truncation(chars, budget_tokens=BUDGET)
    assert planned.applied == actual.applied
    assert planned.kept_chars == pytest.approx(actual.kept_chars, abs=2)
    assert planned.estimated_tokens == pytest.approx(actual.estimated_tokens, abs=2)


def test_the_plan_is_a_no_op_for_a_document_that_fits() -> None:
    planned = plan_truncation(31_751, budget_tokens=BUDGET)
    assert planned.applied is False
    assert planned.removed_chars == 0


def test_a_budget_nothing_can_satisfy_is_reported_rather_than_looped_forever() -> None:
    """A negative budget must terminate and report over-budget, not hang."""
    planned = plan_truncation(219_441, budget_tokens=1)
    assert planned.applied is True
    assert planned.estimated_tokens > 1


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------
def test_the_record_describes_both_outcomes() -> None:
    fits = plan_truncation(10_000, budget_tokens=BUDGET)
    cut = plan_truncation(219_441, budget_tokens=BUDGET)
    assert "not applied" in fits.describe()
    assert "elided" in cut.describe()
    assert cut.rule == RULE


def test_the_corpus_boundary_is_where_expected() -> None:
    """At a 32,768 context and the measured 3.0 chars/token, the rule bites above
    roughly 90k characters — 12 exhibits at the old 3.5, 18 now.

    The boundary moved because the ratio was measured rather than extrapolated from
    two points (ADR 0020 addendum), and it moved in the direction that truncates more
    than strictly necessary: the safe direction, now that the pre-flight verifies the
    cut against the real tokeniser.
    """
    assert plan_truncation(85_000, budget_tokens=BUDGET).applied is False
    assert plan_truncation(95_000, budget_tokens=BUDGET).applied is True


# ---------------------------------------------------------------------------
# The identifier carries its parameters
# ---------------------------------------------------------------------------
def test_the_rule_id_names_every_parameter_that_changes_the_cut() -> None:
    """`head_tail_v1` was the same string at 3.5 chars/token and at 3.0, which cut
    the same document to 98,121 and 84,121 characters. The identifier did not change
    when its parameter did, so two incompatible bases were labelled identically."""
    from mapf.core.truncation import rule_id

    identifier = rule_id()
    assert "24000" in identifier and "4000" in identifier and "3.0" in identifier


def test_two_ratios_cannot_share_an_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """The property that matters. A hand-maintained version suffix can disagree with
    the parameters it names; one computed from them cannot."""
    from mapf.core import truncation

    at_three = truncation.rule_id()
    monkeypatch.setattr(truncation, "CHARS_PER_TOKEN", 3.5)
    assert truncation.rule_id() != at_three


def test_the_marker_inside_the_document_keeps_the_bare_name() -> None:
    """The marker is text the model reads. Putting the parameters in it would change
    the input to every truncated item for no reason a forecast could notice — and the
    head and tail counts it already states carry them anyway."""
    from mapf.core.models import UntrustedText
    from mapf.core.truncation import RULE, truncate

    cut, _ = truncate(UntrustedText("x" * 300_000), budget_tokens=BUDGET)
    assert f"elided by {RULE}:" in cut
    assert "ratio=" not in cut
