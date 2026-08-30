"""The repeat rule: "transient" is a hypothesis, and the ledger tests it (ADR 0024).

A reason classified transient buys an item one retry. A second identical outcome is
not more bad luck — it is the answer — so the item is resolved rather than retried on
every resume, where it would consume the failure allowance afresh each pass and
eventually halt the run on something that can never succeed.

The exclusions are the substance. A reason whose cause is *shared infrastructure*
says nothing about the item when it repeats: five items failed together when DNS
dropped, and what they had in common was the afternoon.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from mapf.corpus.ledger import (
    ALWAYS_RETRIED,
    REPEAT_LIMIT,
    FailureReason,
    Ledger,
    LedgerEntry,
    is_terminal,
)

DAY = date(2026, 1, 21)


def _ledger(tmp_path: Path) -> Ledger:
    return Ledger(tmp_path / "ledger.jsonl")


def _fail(ledger: Ledger, reason: FailureReason, *, ticker: str = "ALLY", day: date = DAY) -> None:
    ledger.append(
        LedgerEntry(ticker=ticker, band="clean", filing_date=day, status="failed", reason=reason)
    )


def _complete(ledger: Ledger, *, ticker: str = "ALLY", day: date = DAY) -> None:
    ledger.append(
        LedgerEntry(
            ticker=ticker,
            band="clean",
            filing_date=day,
            status="complete",
            run_id=uuid4(),
        )
    )


# ---------------------------------------------------------------------------
# One retry, then the answer
# ---------------------------------------------------------------------------
def test_a_single_transient_failure_is_still_retried(tmp_path: Path) -> None:
    """The retry is what tests the hypothesis. Removing it would make every
    transient reason terminal, which is the opposite defect."""
    ledger = _ledger(tmp_path)
    _fail(ledger, "budget_exhausted")
    assert ledger.completed() == set()


def test_the_same_reason_twice_resolves_the_item(tmp_path: Path) -> None:
    """ALLY, exactly: 12,000 analyst reasoning tokens on two separate runs, against
    a maximum of 9,094 across every other item of the band."""
    ledger = _ledger(tmp_path)
    _fail(ledger, "budget_exhausted")
    _fail(ledger, "budget_exhausted")
    assert ("ALLY", "clean", DAY) in ledger.completed()


def test_an_exhausted_item_is_not_reported_as_terminal(tmp_path: Path) -> None:
    """A weaker claim, kept separate. `missing_exhibit` says the filing has no
    exhibit; this says only that we stopped asking."""
    ledger = _ledger(tmp_path)
    _fail(ledger, "budget_exhausted")
    _fail(ledger, "budget_exhausted")
    entry = ledger.resolved()[("ALLY", "clean", DAY)]
    assert not is_terminal(entry.reason)
    assert ("ALLY", "clean", DAY) in ledger.exhausted()


def test_two_different_reasons_are_two_hypotheses_not_one_answer(tmp_path: Path) -> None:
    """An item that failed once on the model and once on the network has one of
    each. Counting them together would resolve an item nothing was confirmed about."""
    ledger = _ledger(tmp_path)
    _fail(ledger, "budget_exhausted")
    _fail(ledger, "other")
    assert ledger.completed() == set()


def test_a_success_after_failures_wins(tmp_path: Path) -> None:
    """The retry worked, which is the case the rule exists to preserve."""
    ledger = _ledger(tmp_path)
    _fail(ledger, "other")
    _complete(ledger)
    entry = ledger.resolved()[("ALLY", "clean", DAY)]
    assert entry.status == "complete"
    assert ledger.exhausted() == {}


def test_the_limit_is_one_retry(tmp_path: Path) -> None:
    assert REPEAT_LIMIT == 2


# ---------------------------------------------------------------------------
# The exclusions
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("reason", sorted(cast("set[FailureReason]", ALWAYS_RETRIED)))
def test_shared_infrastructure_failures_are_retried_forever(
    tmp_path: Path, reason: FailureReason
) -> None:
    """A DNS drop took five items down together. What they shared was the network,
    not a property of any filing, so a second outage across two resumes must not
    burn all five permanently."""
    ledger = _ledger(tmp_path)
    for _ in range(6):
        _fail(ledger, reason)
    assert ledger.completed() == set()


def test_an_edgar_refusal_is_not_excluded(tmp_path: Path) -> None:
    """The server answered. A 404 is EDGAR's view of this filing and it is the same
    view next pass, so a repeat here IS evidence about the item."""
    ledger = _ledger(tmp_path)
    _fail(ledger, "exhibit_error")
    _fail(ledger, "exhibit_error")
    assert ("ALLY", "clean", DAY) in ledger.completed()


def test_the_two_exhibit_reasons_are_classified_apart(tmp_path: Path) -> None:
    """The prerequisite for the whole rule. Until they were separated, a network
    failure fetching an exhibit landed in the same bucket as a model failure."""
    assert "exhibit_unreachable" in ALWAYS_RETRIED
    assert "exhibit_error" not in ALWAYS_RETRIED


def test_one_item_exhausting_does_not_resolve_another(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _fail(ledger, "budget_exhausted", ticker="ALLY")
    _fail(ledger, "budget_exhausted", ticker="ALLY")
    _fail(ledger, "budget_exhausted", ticker="AAPL")
    done = ledger.completed()
    assert ("ALLY", "clean", DAY) in done
    assert ("AAPL", "clean", DAY) not in done


def test_the_same_ticker_on_a_different_filing_is_a_different_item(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _fail(ledger, "budget_exhausted", day=DAY)
    _fail(ledger, "budget_exhausted", day=date(2026, 4, 21))
    assert ledger.completed() == set()
