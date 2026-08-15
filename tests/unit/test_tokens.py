"""Token estimation and the fit gate.

This feeds a refusal, so the two errors are not symmetric: over-estimating costs a
needless warning, under-estimating costs a night. The tests check that the estimate
errs in the safe direction and that the binding agent is named.
"""

from __future__ import annotations

import pytest

from mapf.eval.tokens import (
    CHARS_PER_TOKEN,
    TEMPLATE_RESERVE,
    AgentBudget,
    check_fit,
    estimate_tokens,
)


# ---------------------------------------------------------------------------
# The estimate, calibrated against real rejections
# ---------------------------------------------------------------------------
def test_the_estimate_is_pessimistic_against_the_measured_ratios() -> None:
    """ALLY: 51,188 chars was reported by the server as 13,830 tokens (3.70
    chars/token). The gate must not estimate fewer tokens than that."""
    assert estimate_tokens(51_188) >= 13_830


def test_the_estimate_is_pessimistic_for_the_largest_exhibit() -> None:
    """FCX: 131,879 chars, reported around 33,000 tokens."""
    assert estimate_tokens(131_879) >= 33_000


def test_the_ratio_errs_towards_more_tokens() -> None:
    """Financial prose tokenises worse than ordinary English — figures, tickers and
    table punctuation all split badly — so the gate uses the low end of the range."""
    assert CHARS_PER_TOKEN <= 3.7


def test_a_string_and_its_length_estimate_identically() -> None:
    text = "reconciliation " * 500
    assert estimate_tokens(text) == estimate_tokens(len(text))


def test_an_empty_document_costs_almost_nothing() -> None:
    assert estimate_tokens("") == 1


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------
def test_a_configured_max_tokens_is_reserved_in_full() -> None:
    """Generation shares the window with the prompt. Reserving less than the whole
    budget is how a run dies at the context ceiling while reporting exhaustion."""
    budget = AgentBudget(agent="analyst", context_tokens=32_768, max_tokens=12_000)
    assert budget.output_reserve == 12_000
    assert budget.document_budget == 32_768 - TEMPLATE_RESERVE - 12_000


def test_an_unset_max_tokens_still_reserves_room_for_output() -> None:
    budget = AgentBudget(agent="intake", context_tokens=32_768, max_tokens=None)
    assert budget.output_reserve > 0
    assert budget.document_budget < 32_768


def test_the_intake_budget_at_the_configured_context_admits_the_corpus_median() -> None:
    """Median exhibit is ~31,751 chars; it must fit with room to spare."""
    budget = AgentBudget(agent="intake", context_tokens=32_768, max_tokens=None)
    assert estimate_tokens(31_751) < budget.document_budget


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
def _budgets() -> list[AgentBudget]:
    return [
        AgentBudget(agent="intake", context_tokens=32_768, max_tokens=None),
        AgentBudget(agent="analyst", context_tokens=32_768, max_tokens=12_000),
    ]


def test_a_small_document_fits_with_headroom() -> None:
    result = check_fit(estimate_tokens(5_000), _budgets())
    assert result.fits is True
    assert result.headroom > 0


def test_the_tightest_agent_is_the_binding_one() -> None:
    """Naming it turns 'it will not fit' into 'raise this one number'."""
    result = check_fit(estimate_tokens(5_000), _budgets())
    assert result.binding_agent == "analyst"


def test_an_oversized_document_reports_how_far_over_it_is() -> None:
    budget = [AgentBudget(agent="intake", context_tokens=8_192, max_tokens=None)]
    result = check_fit(estimate_tokens(131_879), budget)
    assert result.fits is False
    assert result.headroom < 0
    assert -result.headroom > 30_000


def test_the_largest_corpus_exhibit_does_not_fit_32k() -> None:
    """BXP at 219,441 chars is the item that forces the truncation rule."""
    budget = [AgentBudget(agent="intake", context_tokens=32_768, max_tokens=None)]
    assert check_fit(estimate_tokens(219_441), budget).fits is False


def test_the_largest_corpus_exhibit_fits_64k() -> None:
    budget = [AgentBudget(agent="intake", context_tokens=65_536, max_tokens=None)]
    assert check_fit(estimate_tokens(219_441), budget).fits is True


def test_a_document_exactly_at_the_budget_fits() -> None:
    budget = [AgentBudget(agent="intake", context_tokens=32_768, max_tokens=None)]
    exact = budget[0].document_budget
    assert check_fit(exact, budget).fits is True
    assert check_fit(exact + 1, budget).fits is False


def test_no_budgets_is_a_programming_error_not_a_pass() -> None:
    with pytest.raises(ValueError, match="no agent budgets"):
        check_fit(100, [])
