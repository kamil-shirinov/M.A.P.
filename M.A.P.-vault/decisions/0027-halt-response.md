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

## Addendum, 2026-09-01 — the conditioning, its bound, and the length control

### Every forecast in the band is conditioned on the analyst terminating

This is a property of the **corpus**, not of any item. All 350 forecasts exist because
the analyst finished inside its budget on the draw that produced them. The runaway is
where that conditioning becomes visible, and it becomes visible in two opposite
directions:

| | items | what the conditioning did |
| --- | --- | --- |
| **removed** | ACGL 2026-02-09, ALLY 2026-01-21, WH 2026-04-29 | ran away twice, resolved by the repeat rule, absent from the sample |
| **left a trace** | CHD 2026-07-31 | ran away once, succeeded on the next draw — its forecast is a resample |

### The bound is two rates, not one

They answer different questions and only both together bound anything:

| | figure | denominator |
| --- | --- | --- |
| **per-attempt runaway rate** | **7 / 358 = 1.96%** | ledger entries that reached the analyst — larger than 356 because ACGL, ALLY, WH and CHD each reached it twice |
| **per-item exclusion rate** | **3 / 356 = 0.84%** | corpus items, of which ACGL, ALLY and WH were removed |

Two of the 358 were served from the response cache on a re-run rather than drawn afresh;
on fresh draws alone the rate is 7/356 = 1.97%, so the distinction does not move it.

**A rate on its own invites the assumption that the exclusion is random, and it is not
known to be.** What is known:

- **Ruled out as a size effect.** Five of the six runaway documents have a same-company,
  same-template sibling that is larger and terminated normally, and every failure but
  ALLY's sits between the 53rd and 73rd percentile of corpus document size.
- **Differential exclusion on content: untested.** Whether the three removed items differ
  systematically from the 351 kept is exactly what the redundancy analysis will answer,
  and it has not been run. Until then the excluded set is **not** assumed random.
- **No sector clustering is visible** — insurance, banking, hotels — but n = 3 supports
  no claim in either direction and is recorded only so nobody reads its absence as
  evidence.

**The DNS four are not part of this.** CP, ELV, LVS and WAL failed before any model call
completed — the exhibit fetch failed — so their retry produced a *first* successful draw,
not a second one. Grouping them with CHD would inflate a selection effect with four items
that carry none.

### Size is ruled out: the runaway is a property of the document's content

The obvious hypothesis is that long documents run away. It is wrong, and the corpus
contains its own within-company control — every one of these companies has other filings
that passed:

| ticker | failing doc | percentile | a **larger** filing that passed |
| --- | --- | --- | --- |
| ACGL | 39,253 | 71st | 39,655 *(and 39,218 passed — 35 chars smaller than the failure)* |
| WH | 39,902 | 73rd | **48,922** |
| CHD | 34,467 | 60th | **41,187** |
| JAZZ | 32,599 | 53rd | **41,625** |
| ATI | 36,261 | 64th | **37,979** |
| ALLY | 51,188 | 90th | — *(the one case where the failure is that company's largest)* |

**In five of six cases the same company has a strictly larger document that succeeded.**
Every failure but ALLY's sits between the 53rd and 73rd percentile of corpus document
size — the median band, not the tail. Against a corpus median of 31,751 characters and a
maximum of 219,441, none of these is a large document.

So a larger budget is not the remedy for a document-size problem, because there is no
document-size problem. **The cause is content**, and the [ADR 0021](0021-degeneration-retry.md)
diagnosis of intake — 757 lines of which 22 were unique — is the shape to look for.

### This table is the control group for the diagnosis

**Recorded here so it is not rediscovered when the diagnostic runs**, which is now
`scripts/analyst_runaway_replay.py` and is built around **ACGL rather than ALLY**:

    ACGL 2026-02-09   39,253 chars   FAILED
    ACGL 2026-04-28   39,218 chars   passed

**Thirty-five characters apart**, same company, same filing type, adjacent quarters,
opposite outcomes. Nothing else in the corpus separates content from size so cleanly, and
it is the strongest natural experiment available.

**ALLY is deliberately not the primary case.** It is the one failure that is its own
company's largest document, so the sibling comparison has no sibling for it — designing
around ALLY would have meant designing around the single item where the control does not
exist. It stays a case to explain once the mechanism is known.

## Addendum, 2026-09-01 (later) — PRU, and a measurement that falsifies the input hypothesis

### PRU is ambiguous and is recorded as ambiguous

PRU 2026-04-14 succeeded under the corrected basis, so by the pre-commitment above it is
scored and the clean band's failures fall to five. **What it does not do is support the
size conclusion**, and it sits in mild tension with it:

- The corrected basis handed PRU **~21,000 fewer characters** than the old one. That is a
  **within-document** input-volume effect, whereas "size is ruled out" was established
  **across documents**, by same-company siblings. The two are different claims and only
  the second is supported.
- It is **one draw at temperature 0.7**. A lucky redraw produces exactly this observation,
  and PRU had failed only once, so nothing distinguishes the two explanations.

Stated precisely: **ruled out as the sole across-document explanation; within-document
input volume untested; PRU is n = 1 and ambiguous.**

### The input-redundancy hypothesis is falsified, measured before any replay

All twelve documents — six failures and a passing same-company sibling for each — were
fetched and measured directly. No inference, hashes verified against the frozen record.

| metric | failures | siblings |
| --- | --- | --- |
| gzip ratio (lower = more redundant) | 0.306 | **0.300** |
| duplicate-line fraction | 51.8% | 51.9% |
| repeated 8-gram fraction | 9.5% | **10.9%** |

**Document redundancy does not separate the two groups, and on two of three measures the
direction is mildly opposite.** Only 2 of 6 failing documents are more compressible than
their sibling; only 1 of 6 has more repeated 8-grams.

### A null is only informative if the measure had range, so both were checked

**Spread across the twelve.** A group gap of 0.005 could mean two groups that genuinely
do not differ, or a measure saturated by HTML table structure with nothing left to move.
Those look identical in a mean:

| measure | min | median | max | spread | group gap |
| --- | --- | --- | --- | --- | --- |
| gzip ratio | 0.268 | 0.303 | 0.334 | **0.065** | 0.005 |
| duplicate-line | 0.471 | 0.517 | 0.565 | **0.094** | 0.002 |
| repeated 8-gram | 0.068 | 0.110 | 0.138 | **0.070** | 0.014 |

The twelve documents vary among themselves by **5× to 47× the failure/pass gap**. The
measures are not saturated.

**Positive control** — the corpus's largest exhibit against its smallest, a pair that
must differ if the measures work at all:

| | chars | gzip | dup-line | rep-8gram |
| --- | --- | --- | --- | --- |
| BXP 2026-01-28 (property tables) | 219,441 | 0.264 | 57.4% | 29.3% |
| IREN 2025-08-28 | 652 | 0.457 | 7.1% | 41.5% |
| **control gap** | | **0.192** | **0.503** | **0.122** |

Every gap exceeds the twelve-document spread, so **all three measures have demonstrated
range.** This is [[../Findings & Incidents#8]]'s guard: a check that can pass vacuously is
worse than no check.

**One caveat, recorded rather than smoothed.** `rep-8gram` is *higher* on the 652-character
document — with so few 8-grams, boilerplate dominates. Its range is demonstrated but its
interpretation on very short documents is unsound. It is not a concern for the twelve,
which all sit between 32k and 51k characters, and gzip and dup-line behave on the control
exactly as redundancy measures should.

**Verdict: not detected by measures with demonstrated range.** That is a falsification of
the input hypothesis, not an untested one. Had the control failed, the correct wording
would have been *"measures inadequate, hypothesis untested"* and the twelve-document
result would have been void.

**What this does not settle.** It measures the **input**. The [ADR 0021](0021-degeneration-retry.md)
intake diagnosis measured the **output** — 757 lines of which 22 were unique — and that
remains entirely open for the analyst. The falsified claim is that redundant input causes
the runaway; the claim that the *reasoning* degenerates is untouched and is what the
replay now exists to test.

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
