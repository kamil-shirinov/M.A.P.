# 0027 — What happens when the failure threshold trips

**Status:** accepted · **Date:** 2026-08-30 · **Pre-registered before the halt** · **Builds on** [0018](0018-corpus-band-and-panel-shape.md), [0019](0019-corpus-execution-protocol.md), [0021](0021-degeneration-retry.md), [0024](0024-repeat-rule.md)

## Context

78 items into the clean band, the permanent failure rate projects past the allowance:

| | permanent failures | rate | projected at 356 | allowance of 8 crossed at |
| --- | --- | --- | --- | --- |
| now | ALLY, ATI | 2/78 = **2.56%** | 9.1 | item **312** |
| if ACGL's retry also fails | + ACGL | 3/78 = **3.85%** | 13.7 | item **208** |

The five `other` failures from the DNS drop all completed on retry and correctly
charge nothing ([ADR 0024](0024-repeat-rule.md)).

This document is written **before** the threshold trips, because the decision it
records cannot be made afterwards without becoming the thing it exists to prevent.

## Decision

### 1 · The halt is the mechanism working. It is not overridden.

The allowance was set in [ADR 0019](0019-corpus-execution-protocol.md) before any
item ran, precisely so it could not be moved once failures were visible. **Raising it
now would be a threshold tuned on the result** — the same researcher degree of
freedom refused when the forecast digest could have been made to stop firing by
trimming its exclusion list until the band's split disappeared.

An argument for raising it can be constructed: the cumulative count and the
consecutive-failure check answer different questions, and a slow accumulation of
*individually diagnosed, heterogeneous* terminal failures is not the systematic fault
the threshold was aimed at. That argument may even be right. **It was reached while
looking at these three failures, and that is disqualifying on its own** — so it is
recorded here as a thing that was considered and rejected on procedural grounds, not
adopted.

### 2 · What a halt actually costs

Power for the primary result — calibration on the clean band ([ADR 0018](0018-corpus-band-and-panel-shape.md)),
computed on the reportable subset, 200 trials so ±3–4 pp of Monte Carlo error:

| scenario | items | reportable | calendar span | k=0.2 | k=0.5 | **k=0.58** | k=0.8 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **full band** | 356 | 90 | 216 d | 100% | 86% | **73%** | 28% |
| **halt @ 312** | 312 | 79 | 209 d | 100% | 92% | **76%** | 32% |
| **halt @ 208** | 208 | 53 | 123 d | 100% | 69% | **53%** | 18% |

The design reproducing ADR 0018's published table is 120 tickers × 3 dates on the
**reportable ~90**, not the full 344 — the corpus is sized on 344 and reported on a
quarter of it, which is what `power.py` exists to keep honest.

Reading these:

- **k = 0.2 survives every halt at 100%.** The five-times overconfidence the first
  live run actually produced would be detected on any of these subsets.
- **A halt at 312 costs nothing measurable.** 76% against 73% is within Monte Carlo
  error of the full band — the two are indistinguishable, and it is not evidence that
  stopping early is *better*.
- **A halt at 208 costs the primary result at the k that matters.** At k = 0.58, the
  pre-registered expected reading for a model stating unconditional volatility on
  earnings windows, power falls **73% → 53%** — from more-likely-than-not to a coin
  flip.

### 3 · The halt also truncates the calendar, and that is worse than the power loss

`plan()` orders items by `(filing_date, ticker)`, so the clean band runs in date
order. A halt does not take a random subset — it takes a **prefix of the year**:

| halt | dates covered | filings per ticker | tickers |
| --- | --- | --- | --- |
| @ 208 | 2026-01-02 → **2026-05-05** | 1.73 | 120 of 120 |
| @ 312 | 2026-01-02 → 2026-07-30 | 2.60 | 120 of 120 |
| full | 2026-01-02 → 2026-08-06 | 2.97 | 120 of 120 |

A halt at 208 **loses May through August entirely.**

This is exactly the confound `passes.py` was built to prevent, arriving through a
door nobody guarded. Its own docstring says taking the first half of the plan "would
make it a calendar-contiguous subsample — roughly H1 of the band — so stopping after
it would confound *we stopped early* with *we only measured the first half of the
year*." **That protection was built for the two-pass ambiguous band and the clean
band does not have it.** The band carrying the primary result is the one run straight
through.

So a halt at 208 yields 53% power *on a seasonally biased subsample*, which is worse
than 53% power on a representative one. Ticker coverage is unaffected — all 120
survive any halt, because every ticker files in Q1 — so what is lost is calendar
span and filings per ticker, not breadth.

**Fixed, not merely recorded — see [ADR 0028](0028-execution-order.md).** The
remaining items are executed in a seeded interleave, so any halt from here leaves a
sample of the year rather than a prefix of it. The 80 already run stay as they are and
the result is a **hybrid**: 80 contiguous early items plus an interleaved remainder,
stated as that rather than claimed as a clean design.

### 4 · The remedy, decided now and conditional on evidence

The remedy branches on what the recorded evidence shows at the halt. Written now this
is a conditional plan; written at item 208 it would be tuning.

**If `output_truncated` failures are loops that a 0.3 penalty does not break** —
ATI's recorded trace shows intake at 2,048 tokens and 57% redundancy, retried at
`frequency_penalty=0.3` to 2,048 tokens and 41% redundancy, still cut off, while the
same 0.3 rescued STZ (72% → 6%) and FCX (58% → 2%) —

> **escalate the ladder: 0.3 → 0.6, one further attempt.** 0.6 is the value already
> measured to rescue both STZ and FCX in the [ADR 0021](0021-degeneration-retry.md)
> table, so it is not a new number chosen after seeing ATI. Recorded per item and
> carried into the ADR 0021 sensitivity partition, exactly as the first rung is: an
> item rescued at 0.6 sampled differently from the rest and is reported both ways.

**If `budget_exhausted` failures are loops** — repeated blocks in the analyst's
recorded reasoning —

> **a penalty retry at the analyst, mirroring ADR 0021 one agent up**, at the same
> 0.3 → 0.6 ladder, with the same per-item recording and the same sensitivity
> partition.

**If they are genuine length** — long, non-repetitive reasoning —

> **raise the analyst budget.** 16,384 less a ~1,600-token prompt leaves room for
> ~14,000. That is a **freeze amendment in its own commit before any further
> inference**, it invalidates every cache key, and the already-completed items are
> either re-run or reported as a **separate stratum** — never silently pooled with
> items produced under a different budget.

**If the evidence is ambiguous**, the ADR 0021 precedent governs: the failure stays
terminal, the items are reported as failures, and no parameter moves on a hypothesis
the data does not support.

### 5 · The evidence this plan will act on does not exist yet

Stated here rather than discovered while executing.

`ModelBudgetExhaustedError` was raised while parsing the response, and the trace
write sat after it — so **a budget-exhausted call left no trace event at all.** The
reasoning text was never captured on any call either. ALLY's two runs and ACGL's run
each hold a single `intake` event and nothing for the analyst.

**So ALLY, ACGL and ATI's budget failures cannot be diagnosed. Their reasoning is
gone.** ATI is the exception and only partially: its *intake* redundancy was recorded
because that failure mode does reach the trace.

Both gaps are now closed. But the running process holds the pre-fix code in memory,
so **every item it writes until it restarts still records nothing on a budget
failure. The first diagnosable budget failure arrives only after a restart.**

The consequence for this plan: **if the halt arrives before any restart, the evidence
branch cannot be evaluated and the correct action is to restart and continue, not to
guess.** A halt at 312 would very likely fall in that category; a halt at 208 might
not.

## Consequences

- On halting: run `scripts/ally_reasoning_replay.py` and the redundancy analysis over
  every budget-exhausted failure recorded *after* the fix. Then take the branch in §4.
- **The leakage estimate needs the ambiguous band, which has not started.** A halt in
  the clean band leaves the headline number uncomputable until the ambiguous band runs
  under its own separate allowance.
- A halt at 312 or later is accepted as substantively complete: indistinguishable
  power, one week of calendar lost.
- A halt at 208 is not accepted as a result on power grounds: 53% at k = 0.58 is a
  coin flip on the pre-registered expected reading, and the remedy must let the band
  complete.

## Addendum · Band pairing when one band halts and the other does not

The leakage estimate is a clean-versus-ambiguous difference, and what protects it is
**same-ticker, same-shape construction** ([ADR 0018](0018-corpus-band-and-panel-shape.md)) —
not per-item pairing, since `aggregate.leakage` takes an unpaired difference of band
means. A clean band halted at 208 compared against a complete ambiguous band is a
comparison of two differently-shaped subsets, and the difference then carries a
composition effect that no interval accounts for.

Decided now, because choosing at the halt is choosing with the numbers in view.

> **Truncate the ambiguous band to match the surviving clean set** — the same
> tickers, the same number of filings per ticker, matched by quarter — and report the
> leakage estimate on the matched pair with both n's stated.

The argument is that this costs nothing that matters. **The ambiguous band exists
only for this comparison**; ADR 0018 is explicit that it "is never a second result".
So discarding unmatched ambiguous items forfeits no finding — only compute already
spent — while restoring the construction the estimate depends on. Reporting leakage as
unavailable, the alternative, forfeits the headline number to protect against a
composition effect that matching removes.

**The fallback, and its condition, stated now.** If matching leaves fewer than one
filing per ticker for a material share of tickers — so the matched set is no longer
the same-ticker panel the design assumes — **leakage is reported as unavailable**
rather than as an adjusted number. A matched panel that has quietly become a
different panel is the failure the matching was meant to prevent.

**One thing the interleave changes here.** With execution in a seeded random order,
the surviving clean set is an unbiased random sample of its band, so the clean mean
is an unbiased estimate of the clean-band mean and the leakage difference stays
unbiased — wider, not skewed. Under the old prefix order it was seasonally biased and
matching would have had to correct a bias rather than a shape. **The ordering fix and
the pairing decision are the same repair seen from two sides.**

## Addendum · An observation about the two-pass continuation option

ADR 0019 offers stopping after pass one as a legitimate outcome decided on time.
**The runner has no notion of passes** — `split_passes` is computed at scoring time
from the planned order, and `run_band` executes the whole band. So under date order
a stop partway gave half of each pass rather than all of pass one, and the
continuation option was already not executable as described.

The interleave does not change that either way. Recorded here because it is adjacent
and would otherwise be found while trying to exercise it.
