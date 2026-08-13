"""The cutoff probe's classifiers.

A probe that misreads responses measures its own regex, not the model. Both
classifiers are tested against the shapes real models actually produce — including
the one that matters most: a hedge containing the word "no".
"""

from __future__ import annotations

from datetime import date

import pytest

from mapf.eval.cutoff import (
    EventItem,
    MonthResult,
    estimate_boundary,
    is_hedge,
    parse_yes_no,
    summarise,
)


# ---------------------------------------------------------------------------
# Hedge detection — the ground-truth-free signal
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "response",
    [
        "I don't have information about events after my training cutoff.",
        "I do not have access to data from that period.",
        "As of my last update, I cannot confirm this.",
        "My knowledge cutoff is in 2024, so I am unable to provide that.",
        "That is beyond my training data.",
        "My data only goes up to early 2024.",
        "I cannot verify events from that month.",
    ],
)
def test_a_declining_response_is_a_hedge(response: str) -> None:
    assert is_hedge(response) is True


@pytest.mark.parametrize(
    "response",
    [
        "NVIDIA announced record data centre revenue that month.",
        "Yes. The acquisition completed in that period.",
        "No, that did not happen.",
        "Apple released a new iPhone.",
    ],
)
def test_a_confident_answer_is_not_a_hedge(response: str) -> None:
    assert is_hedge(response) is False


def test_a_hedge_containing_the_word_no_is_still_a_hedge() -> None:
    """The case that would otherwise silently corrupt the accuracy curve: a decline
    that happens to contain a verdict word. Hedging is checked first for this."""
    response = "I don't have information after my training cutoff, but generally no."
    assert is_hedge(response) is True
    assert parse_yes_no(response) is None


# ---------------------------------------------------------------------------
# Verdict parsing — the EDGAR-grounded signal
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("YES", True),
        ("yes", True),
        ("Yes, that is correct.", True),
        ("NO", False),
        ("No, it did not.", False),
        ("Maybe, it is unclear.", None),
        ("Yes and no.", None),
        ("", None),
    ],
)
def test_verdict_parsing(response: str, expected: bool | None) -> None:
    assert parse_yes_no(response) == expected


def test_only_the_head_of_a_rambling_answer_is_parsed() -> None:
    """A reasoning model can talk itself into both verdicts if given enough rope."""
    response = "No." + " padding." * 200 + " yes"
    assert parse_yes_no(response) is False


# ---------------------------------------------------------------------------
# Summarising — keeping the two signals independent
# ---------------------------------------------------------------------------
def test_accuracy_is_computed_over_answered_items_only() -> None:
    """Scoring an unanswered item as wrong would fold the hedge signal into the
    accuracy signal, destroying exactly the independence that makes running two
    methods worthwhile."""
    result = summarise(
        date(2025, 3, 1),
        hedges=[True, False, False],
        verdicts=[(None, True), (True, True), (False, True)],
    )
    assert result.answered == 2
    assert result.accuracy == pytest.approx(0.5)
    assert result.hedge_rate == pytest.approx(1 / 3)


def test_a_month_with_no_answers_has_undefined_accuracy() -> None:
    """None, not zero. Zero would read as "the model was wrong" when it declined."""
    result = summarise(date(2025, 3, 1), hedges=[True], verdicts=[(None, True)])
    assert result.accuracy is None


# ---------------------------------------------------------------------------
# The two boundary estimates stay separate
# ---------------------------------------------------------------------------
def test_the_two_methods_produce_two_estimates() -> None:
    """Deliberately not reconciled. A caller that averaged them would hide the
    disagreement that tells us the boundary is soft."""
    results = [
        MonthResult(date(2024, 1, 1), hedge_rate=0.0, accuracy=0.9, answered=4, total=4),
        MonthResult(date(2024, 6, 1), hedge_rate=0.1, accuracy=0.5, answered=4, total=4),
        MonthResult(date(2025, 1, 1), hedge_rate=0.8, accuracy=0.4, answered=2, total=4),
    ]
    hedge_month, accuracy_month = estimate_boundary(results)
    assert hedge_month == date(2025, 1, 1)
    assert accuracy_month == date(2024, 6, 1)
    assert hedge_month != accuracy_month  # a soft boundary, and the caller must see it


def test_a_model_that_never_hedges_has_no_hedge_boundary() -> None:
    """A flat curve is not a boundary at zero. None means "this method found
    nothing", which per ADR 0013 must never read as "no contamination"."""
    results = [
        MonthResult(date(2024, m, 1), hedge_rate=0.0, accuracy=0.9, answered=4, total=4)
        for m in (1, 6, 12)
    ]
    assert estimate_boundary(results) == (None, None)


def test_an_event_item_records_its_edgar_provenance() -> None:
    item = EventItem(
        "Apple Inc.",
        320193,
        "completed an acquisition",
        date(2025, 3, 1),
        True,
        "0000320193-25-000001",
    )
    assert item.accession is not None


# ---------------------------------------------------------------------------
# Probe budgets inherit rather than being configured beside the pipeline's
# ---------------------------------------------------------------------------
def test_a_probe_inherits_the_agent_budget() -> None:
    """The probe ran at 2,500 tokens while the pipeline ran at 12,000, and the
    analyst exhausted its budget mid-reason on every open question — holes in
    exactly the curve that mattered most. Two numbers that had to move together
    and did not, the same defect as the max_tokens/read_timeout pair."""
    from mapf.eval.cutoff import probe_budget

    assert probe_budget(12000) == 12000
    assert probe_budget(2500) == 4000  # floored: a probe is never tighter than this


def test_an_unconfigured_agent_gets_the_floor() -> None:
    """No configured ceiling means the pipeline is relying on a server default the
    probe cannot see, so it must not guess low."""
    from mapf.eval.cutoff import probe_budget

    assert probe_budget(None) == 4000
