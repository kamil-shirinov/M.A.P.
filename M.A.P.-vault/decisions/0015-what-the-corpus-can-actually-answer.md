# 0015 — What a feasible corpus can actually answer

Status: Accepted · Date: 2026-08-13 · Phase 2

## Context

The Phase 2 brief sizes the corpus at 30 tickers × 8 dates ≈ 240 forecasts and
names CRPS against a random walk as the primary result. The power analysis was run
first, before any corpus construction, to check that this is answerable.

**It is not.** But a different and arguably better question is.

## Method

The calendar is simulated rather than the correlation. Windows on different tickers
that overlap in time share market moves, and staggering dates does not remove
that — two windows five days apart still share sixteen of twenty-one days. So the
simulation generates daily returns for the whole panel (market factor plus
idiosyncratic, calibrated to ~25% annual volatility and ~0.4 average pairwise
correlation) and sums them over the actual windows.

Scoring is paired: both forecasters see the same market move, so the difference in
their CRPS is driven by how the forecasts differ. Inference is a moving-block
bootstrap over calendar time, which preserves both the cross-sectional and the
serial dependence that resampling individual forecasts would destroy.

The target is the **post-cutoff holdout** — half the panel by ticker, then half
again by cutoff side. **60 forecasts, not 240.**

## Finding 1 — directional skill is not detectable at any feasible corpus size

Power to detect a forecaster whose central estimate correlates with the realised
return at `rho`:

| rho | ΔCRPS | improvement | power at N=60 |
|---|---|---|---|
| 0.05 | -0.0001 | 0.3% | 10% |
| 0.10 | -0.0003 | 0.8% | 17% |
| 0.15 | -0.0007 | 1.6% | 22% |
| 0.20 | -0.0011 | 2.6% | 24% |
| 0.30 | -0.0023 | 5.6% | 41% |
| 0.40 | -0.0040 | 9.5% | 52% |

A correlation of 0.20 between a 21-day forecast and the realised return would be
an exceptional result for any equity forecaster. At 24% power we would fail to
detect it three times in four.

Scaling the corpus does not rescue this. Holding the split fixed and growing the
panel:

| corpus | reportable | power at rho=0.20 | nights at ~9 min/run |
|---|---|---|---|
| 240 | 60 | 26% | 4.5 |
| 480 | 120 | 29% | 9 |
| 960 | 240 | 42% | 18 |
| 1920 | 480 | 64% | 36 |

80% power would need somewhere near 3,000 forecasts — **roughly 60 nights of
compute**, for the *primary* result alone.

## Finding 2 — calibration is detectable at the corpus we already planned

The same 60 forecasts, testing a forecaster with **no directional skill** that
misjudges dispersion by a factor `k`:

| σ predicted / σ true | power | |
|---|---|---|
| 0.2 | **100%** | 5× overconfident |
| 0.5 | **71%** | 2× overconfident |
| 0.7 | 39% | 1.4× overconfident |
| 1.0 | **0%** | correctly calibrated — the test is correctly sized |
| 1.5 | **63%** | 1.5× too wide |
| 2.0 | **97%** | 2× too wide |

The first live run forecast a base-case volatility of 0.05 against AAPL's realised
~0.25 — that is `k = 0.2`, the top row, detectable with certainty at N=60.

## Proposal

**Make calibration the primary question of Phase 2, and directional skill a
secondary, explicitly underpowered one.**

- Primary: is M.A.P. calibrated? PIT histogram, CRPS against the baselines,
  reported with a confidence interval. Answerable at 240 forecasts.
- Secondary: does M.A.P. beat a random walk directionally? Report the point
  estimate and the interval, and **state the power alongside it**, so a null result
  reads as "underpowered" rather than "no skill".

**This is a design choice rather than a compromise, and the reason is that
calibration is the only question with a complete arc.** We can measure the
failure, fix it in Phase 3 with isotonic regression, and then measure the fix on
the same corpus — three steps that close. Directional skill offers only the first
step and not even that reliably: we could fail to measure it and would have no
mechanism to fix it if we did. A question whose answer cannot change what we build
is not worth the compute, however interesting it is.

Calibration is also the property the forecasts are most obviously failing, and a
well-calibrated forecaster with no directional edge is still a useful object. A
directional claim we cannot support at any affordable sample size is not.

## Finding 3 — the horizon should be 5 days, not 21

Tested before freezing the corpus, because 21 days is baked into panel
construction and expensive to revisit.

**Power is horizon-invariant at fixed compute**, which is what theory predicts:
both the signal and the noise scale with the horizon's volatility. At 240
forecasts, power to detect `rho=0.20` was 19% / 14% / 26% at 5 / 10 / 21 days, and
to detect a 2x-overconfident forecast 74% / 78% / 80% — flat within simulation
noise. So the statistical case is neutral and the decision rests elsewhere.

The mechanical case is not neutral at all:

| horizon | sigma over the window | max dates per ticker (2y) | P(ex-dividend in window) |
|---|---|---|---|
| 5 | 0.035 | 99 | **8%** |
| 10 | 0.050 | 49 | 16% |
| 21 | 0.072 | 23 | **33%** |

**A third of all 21-day windows contain an ex-dividend date.** ADR 0013 requires
those to be excluded or separately reported, so the 21-day horizon quietly costs a
third of the reportable sample before anything is scored — 118 down to 79, against
109 at 5 days. Power to detect a 2x calibration error accordingly runs 94% / 87% /
87%.

The second column matters too: at 5 days a two-year calendar yields 99
non-overlapping windows per ticker against 23. Panel shape stops being dictated by
the length of the post-cutoff span, which was the constraint that forced 30x8 in
the first place.

**One argument for the short horizon this simulation cannot test.** Post-earnings
announcement drift is documented at 5-10 days, so true `rho` may well be larger
there — but the simulation takes `rho` as a parameter, so it can say what power we
have at a given skill and nothing about whether the skill is real. That case rests
on the literature, not on anything measured here, and it should be described that
way.

**Decision: 5 trading days.** Chosen for the dividend-contamination and
calendar-freedom arguments, which are measured, with the drift argument as an
untested bonus rather than a justification.

## Consequences

- The 240-forecast corpus stands, and the reweighting below is worth taking:
  **70% holdout and 70% post-cutoff** rather than 50/50, which lifts the reportable
  sample from 60 to about 118 at no extra compute. Pre-cutoff items are only needed
  in the number required to *measure* leakage, not in equal share.
- Every reported null result must carry its power. A confidence interval spanning
  zero at 24% power says nothing about the world.
- **One experiment here is inconclusive and should not be cited.** Holding the
  corpus fixed and stretching the calendar from 2 to 16 years did not raise power
  (29%, 17%, 20%, 16%). That contradicts theory — sparser windows should be more
  independent — and most likely reflects the bootstrap's fixed 42-day blocks
  becoming mostly empty at low density rather than anything about panel design.
  It needs a variable block size before it means anything.

  **Update 2026-08-13 — the diagnosis was right, and the defect is fixed.**
  `_moving_block_bootstrap` drew block starts uniformly across the span and
  silently discarded the empty draws, so the resample was far smaller than the
  sample. Blocks now begin only on occupied days and are drawn until the resample
  matches the sample size. Re-derived, the figures are **20% / 18% / 13% / 12%** —
  monotone rather than erratic, so the instability is gone and the direction of
  the original conclusion survives.

  **It stays uncited, for a different reason.** It is measured over 2–16 years and
  every live question concerns a 7–20 month band; a result can be sound at one
  scale and irrelevant at another. Where clustering matters it is now measured
  directly on the panel in question (ADR 0018), validated against forced-clustering
  stress cases. This experiment is retained as the record of a fixed bug, not as
  evidence for anything.
- The dominant cost is the analyst at ~6.7 minutes of a ~9 minute run. If
  directional skill ever becomes the priority, that is the number to attack first —
  but not before there is a way to measure whether attacking it made things worse.
