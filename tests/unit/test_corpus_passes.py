"""Pass boundaries for the two-pass ambiguous band.

The assertions are about the properties that keep the continuation rule honest:
passes are reproducible without a seed, each is a spread sample rather than a
calendar slice, scoring refuses on an unfinished pass, and the only quantity the
decision may read carries no outcome.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from mapf.corpus.ledger import Ledger, LedgerEntry
from mapf.corpus.passes import (
    IncompletePassError,
    elapsed_report,
    require_finished,
    split_passes,
    status_of,
)
from mapf.corpus.runner import CorpusItem

TICKERS = [f"T{i:02d}" for i in range(6)]


def _items(n_dates: int = 6) -> tuple[CorpusItem, ...]:
    """Plan order: date, then ticker — the order the runner uses."""
    start = date(2025, 1, 6)
    return tuple(
        CorpusItem(ticker, "ambiguous", start + timedelta(days=30 * d))
        for d in range(n_dates)
        for ticker in TICKERS
    )


def _ledger(tmp_path: Path) -> Ledger:
    return Ledger(tmp_path / "ledger.jsonl")


def _complete(ledger: Ledger, item: CorpusItem, elapsed: float = 500.0) -> None:
    ledger.append(
        LedgerEntry(
            ticker=item.ticker,
            band=item.band,
            filing_date=item.filing_date,
            status="complete",
            elapsed_s=elapsed,
        )
    )


# ---------------------------------------------------------------------------
# Partitioning
# ---------------------------------------------------------------------------
def test_two_passes_cover_every_item_exactly_once() -> None:
    items = _items()
    first, second = split_passes(items, band="ambiguous")
    assert first.size + second.size == len(items)
    assert set(first.items) | set(second.items) == set(items)
    assert not set(first.items) & set(second.items)


def test_the_partition_is_reproducible_without_a_seed() -> None:
    """A pure function of the frozen plan order needs no seed and no record."""
    a = split_passes(_items(), band="ambiguous")
    b = split_passes(_items(), band="ambiguous")
    assert [p.items for p in a] == [p.items for p in b]


def test_each_pass_spans_the_whole_calendar_rather_than_half_of_it() -> None:
    """A contiguous split would confound stopping early with measuring only H1."""
    items = _items()
    all_dates = {i.filing_date for i in items}
    for pass_ in split_passes(items, band="ambiguous"):
        assert {i.filing_date for i in pass_.items} == all_dates


def test_the_halves_are_balanced() -> None:
    first, second = split_passes(_items(), band="ambiguous")
    assert abs(first.size - second.size) <= 1


def test_labels_name_the_band_and_the_half() -> None:
    first, second = split_passes(_items(), band="ambiguous")
    assert (first.label, second.label) == ("ambiguous_half_1", "ambiguous_half_2")


def test_more_than_two_passes_are_labelled_as_passes() -> None:
    passes = split_passes(_items(), band="ambiguous", count=3)
    assert [p.label for p in passes] == [
        "ambiguous_pass_1",
        "ambiguous_pass_2",
        "ambiguous_pass_3",
    ]
    assert all(p.of == 3 for p in passes)


def test_a_single_pass_is_the_whole_band() -> None:
    (only,) = split_passes(_items(), band="clean", count=1)
    assert only.size == len(_items())


def test_a_zero_pass_split_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        split_passes(_items(), band="ambiguous", count=0)


# ---------------------------------------------------------------------------
# Status, read from the ledger and nowhere else
# ---------------------------------------------------------------------------
def test_an_untouched_pass_reports_nothing_resolved(tmp_path: Path) -> None:
    first, _ = split_passes(_items(), band="ambiguous")
    status = status_of(first, _ledger(tmp_path))
    assert (status.complete, status.resolved, status.finished) == (0, 0, False)
    assert status.remaining == first.size


def test_completed_items_are_counted(tmp_path: Path) -> None:
    first, _ = split_passes(_items(), band="ambiguous")
    ledger = _ledger(tmp_path)
    for item in first.items[:3]:
        _complete(ledger, item)
    status = status_of(first, ledger)
    assert status.complete == 3
    assert status.remaining == first.size - 3


def test_a_terminal_failure_resolves_an_item_without_completing_it(
    tmp_path: Path,
) -> None:
    """It will never be retried, so the pass can finish despite it."""
    first, _ = split_passes(_items(), band="ambiguous")
    ledger = _ledger(tmp_path)
    for item in first.items[:-1]:
        _complete(ledger, item)
    last = first.items[-1]
    ledger.append(
        LedgerEntry(
            ticker=last.ticker,
            band=last.band,
            filing_date=last.filing_date,
            status="failed",
            reason="missing_exhibit",
        )
    )
    status = status_of(first, ledger)
    assert status.terminal == 1
    assert status.complete == first.size - 1
    assert status.finished is True


def test_a_transient_failure_leaves_the_pass_unfinished(tmp_path: Path) -> None:
    """It will be retried, so the pass is still outstanding."""
    first, _ = split_passes(_items(), band="ambiguous")
    ledger = _ledger(tmp_path)
    for item in first.items[:-1]:
        _complete(ledger, item)
    last = first.items[-1]
    ledger.append(
        LedgerEntry(
            ticker=last.ticker,
            band=last.band,
            filing_date=last.filing_date,
            status="failed",
            reason="inference_unreachable",
        )
    )
    assert status_of(first, ledger).finished is False


def test_the_other_passs_work_does_not_count(tmp_path: Path) -> None:
    first, second = split_passes(_items(), band="ambiguous")
    ledger = _ledger(tmp_path)
    for item in second.items:
        _complete(ledger, item)
    assert status_of(first, ledger).complete == 0
    assert status_of(second, ledger).finished is True


# ---------------------------------------------------------------------------
# The refusal
# ---------------------------------------------------------------------------
def test_scoring_refuses_while_a_declared_pass_is_outstanding(tmp_path: Path) -> None:
    passes = split_passes(_items(), band="ambiguous")
    ledger = _ledger(tmp_path)
    for item in passes[0].items:
        _complete(ledger, item)
    with pytest.raises(IncompletePassError) as caught:
        require_finished(passes, ledger)
    assert "ambiguous_half_2" in str(caught.value)
    assert "outstanding" in str(caught.value)


def test_the_refusal_names_every_unfinished_pass(tmp_path: Path) -> None:
    passes = split_passes(_items(), band="ambiguous")
    with pytest.raises(IncompletePassError) as caught:
        require_finished(passes, _ledger(tmp_path))
    assert set(caught.value.missing) == {"ambiguous_half_1", "ambiguous_half_2"}


def test_stopping_after_one_half_is_allowed_when_declared(tmp_path: Path) -> None:
    """A declared stop is a legitimate outcome of the continuation rule; the point
    is that it must be declared, so 'we chose to stop' stays distinguishable from
    'it never finished'."""
    passes = split_passes(_items(), band="ambiguous")
    ledger = _ledger(tmp_path)
    for item in passes[0].items:
        _complete(ledger, item)
    statuses = require_finished(passes, ledger, declared=["ambiguous_half_1"])
    assert statuses[0].finished is True
    assert statuses[1].finished is False


def test_a_fully_finished_band_passes(tmp_path: Path) -> None:
    passes = split_passes(_items(), band="ambiguous")
    ledger = _ledger(tmp_path)
    for pass_ in passes:
        for item in pass_.items:
            _complete(ledger, item)
    assert all(s.finished for s in require_finished(passes, ledger))


# ---------------------------------------------------------------------------
# The only quantity the continuation decision may read
# ---------------------------------------------------------------------------
def test_the_elapsed_report_carries_time_and_nothing_else(tmp_path: Path) -> None:
    passes = split_passes(_items(), band="ambiguous")
    ledger = _ledger(tmp_path)
    for item in passes[0].items:
        _complete(ledger, item, elapsed=500.0)
    report = elapsed_report(passes, ledger)
    assert report["ambiguous_half_1"] == pytest.approx(500.0 * passes[0].size)
    assert report["ambiguous_half_2"] == 0.0
    assert set(report) == {"ambiguous_half_1", "ambiguous_half_2"}
    assert all(isinstance(v, float) for v in report.values())
