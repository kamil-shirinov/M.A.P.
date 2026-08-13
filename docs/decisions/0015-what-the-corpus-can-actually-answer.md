# 0015 — What a feasible corpus can actually answer

Status: **Proposed** — needs a decision on Phase 2's primary question · Date: 2026-08-13 · Phase 2

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

This is not a retreat. Calibration is the property the forecasts are most obviously
failing, it is what Phase 3's isotonic regression exists to fix, and a
well-calibrated forecaster with no directional edge is still a useful object. A
directional claim we cannot support at any affordable sample size is not.

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
- The dominant cost is the analyst at ~6.7 minutes of a ~9 minute run. If
  directional skill ever becomes the priority, that is the number to attack first —
  but not before there is a way to measure whether attacking it made things worse.
