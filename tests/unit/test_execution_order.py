"""Execution order, and why it is not the planned order (ADR 0028).

`plan()` orders by `(filing_date, ticker)`. A halt therefore took a **prefix of the
year** rather than a sample of it — at item 208 of the clean band, May through August
were lost entirely.

That is exactly the confound `passes.py` was written to prevent, and its rationale
was in writing before any of these failures: a calendar-contiguous subsample "would
confound *we stopped early* with *we only measured the first half of the year*". The
protection existed; it had been applied to the other band.
"""

from __future__ import annotations

import collections
from datetime import date, timedelta

from mapf.corpus.runner import EXECUTION_SEED, CorpusItem, execution_order


def _band(n: int = 356, tickers: int = 120) -> tuple[CorpusItem, ...]:
    """A band shaped like the real one: dates spread over eight months, plan order
    by date, roughly three filings per ticker."""
    start = date(2026, 1, 2)
    items = [
        CorpusItem(
            ticker=f"T{i % tickers:03d}",
            band="clean",
            filing_date=start + timedelta(days=int(i * 216 / n)),
        )
        for i in range(n)
    ]
    return tuple(sorted(items, key=lambda i: (i.filing_date, i.ticker)))


def _months(items: object) -> collections.Counter[int]:
    return collections.Counter(i.filing_date.month for i in items)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# The property that matters: any prefix spans the calendar
# ---------------------------------------------------------------------------
def test_a_halt_partway_still_covers_every_month() -> None:
    """The prefix order lost four months at item 208. This is the whole point."""
    band = _band()
    order = execution_order(band, set(), seed=EXECUTION_SEED)
    assert len(_months(order[:208])) == len(_months(band))


def test_the_planned_order_does_not_have_that_property() -> None:
    """The control. Without it the assertion above would pass under both the bug and
    the fix, which is not a test (the second lesson, above)."""
    band = _band()
    assert len(_months(band[:208])) < len(_months(band))


def test_an_early_prefix_is_already_spread() -> None:
    band = _band()
    order = execution_order(band, set(), seed=EXECUTION_SEED)
    assert len(_months(order[:40])) >= 7


# ---------------------------------------------------------------------------
# What it must not change
# ---------------------------------------------------------------------------
def test_every_item_is_executed_exactly_once() -> None:
    band = _band()
    order = execution_order(band, set(), seed=EXECUTION_SEED)
    assert sorted(i.key for i in order) == sorted(i.key for i in band)


def test_completed_items_are_excluded_not_reordered() -> None:
    band = _band()
    done = {i.key for i in band[:80]}
    order = execution_order(band, done, seed=EXECUTION_SEED)
    assert len(order) == len(band) - 80
    assert not {i.key for i in order} & done


def test_the_order_is_stable_across_resumes() -> None:
    """The whole band is shuffled and then filtered, rather than the remainder being
    shuffled — so a resume continues the same order instead of drawing a new one."""
    band = _band()
    first = execution_order(band, set(), seed=EXECUTION_SEED)
    done = {i.key for i in first[:50]}
    resumed = execution_order(band, done, seed=EXECUTION_SEED)
    assert resumed == first[50:]


def test_the_order_is_reproducible_from_the_seed_alone() -> None:
    band = _band()
    assert execution_order(band, set(), seed=7) == execution_order(band, set(), seed=7)


def test_a_different_seed_gives_a_different_order() -> None:
    band = _band()
    assert execution_order(band, set(), seed=1) != execution_order(band, set(), seed=2)


def test_an_empty_band_is_handled() -> None:
    assert execution_order((), set(), seed=EXECUTION_SEED) == ()


def test_a_fully_completed_band_yields_nothing_to_run() -> None:
    band = _band(n=10, tickers=5)
    assert execution_order(band, {i.key for i in band}, seed=EXECUTION_SEED) == ()


# ---------------------------------------------------------------------------
# The hybrid, stated rather than hidden
# ---------------------------------------------------------------------------
def test_a_hybrid_band_still_covers_every_month() -> None:
    """The real situation: 80 items already run in date order, the rest interleaved.
    The early months are over-represented and every month is present — which is a
    stateable distortion, unlike three months of complete absence."""
    band = _band()
    done_items = band[:80]
    order = execution_order(band, {i.key for i in done_items}, seed=EXECUTION_SEED)
    halted = list(done_items) + list(order[:130])
    assert len(_months(halted)) == len(_months(band))

    full = _months(band)
    part = _months(halted)
    over = max((part[m] / len(halted)) / (full[m] / len(band)) for m in full if part.get(m))
    # Bounded distortion, not an absence. The prefix order dropped months entirely,
    # which no weighting repairs.
    assert over < 2.0
