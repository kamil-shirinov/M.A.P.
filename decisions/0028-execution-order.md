# 0028 — Execute in a seeded interleave, so a halt leaves a sample and not a prefix

**Status:** accepted · **Date:** 2026-08-30 · **Builds on** [0018](0018-corpus-band-and-panel-shape.md), [0019](0019-corpus-execution-protocol.md), [0027](0027-halt-response.md)

## Context

`plan()` orders a band by `(filing_date, ticker)`, and `run_band` executes it in that
order. So a halt does not take a subset of the band — it takes **a prefix of the
year**. At item 208 of the clean band that is 2026-01-02 to 2026-05-05: **May, June,
July and August absent entirely.**

`passes.py` already says why that is unacceptable, and said it before any of these
failures existed:

> Taking the first half of the plan and calling it pass one would make it a
> calendar-contiguous subsample — roughly H1 of the band — so stopping after it would
> confound "we stopped early" with "we only measured the first half of the year".

**The protection was designed, argued for, written down, and installed on the
ambiguous band.** The clean band — which carries the primary result — runs straight
through.

## Decision

**Execute in a seeded shuffle of the band; leave `plan()` alone.**

### Why this is not a threshold moved after seeing a result

Two independent reasons, and the second is the stronger.

**No score exists anywhere.** Not one forecast has been scored. There is no result to
tune towards, so the objection that defeated raising the failure allowance
([ADR 0027](0027-halt-response.md) §1) has nothing to attach to here.

**And this applies a principle already in writing** to a place it was missed, rather
than inventing one to make an outcome come out. The rationale above predates every
failure in this run. The distinction is exactly the one that made backfilling the
forecast digest legitimate: recovering what a documented rule already implies is not
the same act as choosing a new rule with the answer in view.

### Why execution order cannot affect a single forecast

Worth stating precisely, because it is what makes the change safe to make mid-run:

- `as_of` is derived from the item's filing date, never from a clock or a position.
- The price vintage is pinned in `RunnerConfig`.
- Sampling carries a fixed seed and the cache is keyed on content, not on sequence.
- Models are loaded per item in a fixed intra-item order.

So execution order determines exactly one thing: **which subset survives a halt.**

### Why a seeded shuffle rather than a stride

A stride — every *k*-th item — also spreads the calendar and needs no seed. A shuffle
was chosen because it makes **any prefix an unbiased random sample of the remainder**,
which is a sentence that can appear in a result. A systematic sample is defensible but
requires an argument about whether the stride interacts with the sampling frame; a
random one does not.

The whole band is shuffled and then filtered by what is already done, rather than the
remainder being shuffled. That makes the order a function of the corpus and the seed
alone, so a resume continues the same order instead of drawing a fresh one each time.

### `plan()` is untouched, deliberately

`plan()` defines **pass membership**, which is pre-registered in
[ADR 0019](0019-corpus-execution-protocol.md) and computed at scoring time. Execution
order and pass membership are now separate concerns, and this changes only the first.

## The result is a hybrid, and is reported as one

80 items have already run in date order. They stay. What follows is interleaved, so
the band is **80 contiguous early items plus an interleaved remainder** — stated as
that, never described as a clean interleaved design.

The distortion is bounded and measured. At a halt around item 210:

| | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full band (356) | 36 | 79 | 13 | 67 | 53 | 8 | 67 | 33 |
| **hybrid @ 210** | 36 | 62 | 4 | 32 | 30 | 4 | 29 | 13 |
| prefix @ 208 (old) | 36 | 79 | 13 | 67 | 13 | **0** | **0** | **0** |

**All eight months survive the hybrid**, with January over-weighted about 1.7× and
July–August under-weighted — a distortion that can be stated, bounded, and if
necessary weighted. The prefix loses three months completely, and no weighting
repairs an absence.

That is the answer to whether the hybrid is worse than the prefix: it is not, and the
comparison is not close. A known composition distortion is a different kind of object
from a missing quarter.

## Consequences

- `execution_seed` joins `RunnerConfig` and the frozen record, so the order is
  reproducible from the record alone rather than from the code that happened to run.
- **A freeze amendment in its own commit**, before the next inference. The order does
  not change any forecast, but it changes which forecasts exist if the run stops, and
  that belongs in the record.
- Progress is reported as position in the **band**, not in the invocation, so a
  resume does not print `[3/356]` after two hundred completed items.
- The ambiguous band, which has not started, gets an interleaved order from its first
  item — the clean band's hybrid is a consequence of when this was noticed, not a
  design applied to both.
- **This is also what keeps the leakage estimate valid under a halt.** A random
  subsample gives an unbiased estimate of its band's mean; a seasonal prefix does not.
  See [ADR 0027](0027-halt-response.md)'s pairing addendum.
