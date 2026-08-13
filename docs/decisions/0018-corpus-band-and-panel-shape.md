# 0018 — Which band carries the primary result, and the panel shape that fits it

**Status:** accepted · **Date:** 2026-08-13 · **Builds on** [0015](0015-what-the-corpus-can-actually-answer.md), [0016](0016-five-day-horizon.md), [0017](0017-hedging-measures-metacognition.md)

## Context

ADR 0017 measured the analyst's training boundary at roughly 2025H1 on one signal
(hedge rate) with the second signal silent. That leaves a clean band running from
2026H1 to the present — **about seven months.**

Pairing against a baseline removes the common market move. It does **not** remove
correlation in forecast *error* across a narrow calendar window: if the model is
systematically miscalibrated in one regime, every date inside a seven-month band
shares that miscalibration. So a corpus packed into the clean band buys freedom
from leakage at the price of resting everything on a single regime.

Three questions had to be answered with numbers before any of it was built:
does the band hold enough windows, does date-clustering destroy the power, and
is one regime enough to generalise from.

## Options

1. **Clean band only.** Free of leakage; one regime; seven months.
2. **Widen to include the ambiguous band** (2025H1 onward) for the primary result,
   demoting clean to a robustness check. More regimes, but the primary number is
   computed on possibly-contaminated data.
3. **Admit a second 8-K item type** to raise event supply, recording the
   forecasting-difficulty difference as a covariate.
4. **Clean band for the primary; run the ambiguous band with the identical design
   and report the difference between them as a leakage estimate.**

## Decision

**Option 4.**

### Why the clean band takes the primary, stated as the reasoning and not just the conclusion

**Leakage biases calibration in the flattering direction.** A model that remembers
what happened states a narrow interval and is right. It does not look like a
cheater; it looks like a *well-calibrated forecaster*. The headline claim of Phase 2
is a calibration claim, so contamination would corrupt precisely the number the
project is judged on, in the direction that makes the project look good. That is
the worst possible failure mode for a result meant to be falsifiable.

The regime confound is a different kind of error. It is **bounded, measurable, and
in no particular direction** — it inflates or deflates the measured ratio depending
on whether the band happened to be calmer or wilder than usual, and it can be
reported as a stated adjustment. Trading a fatal, self-flattering bias for a
bounded, directionless one is the right trade, and it would still be the right
trade if the regime penalty were several times larger than it is.

Running the ambiguous band as well converts the contaminated half from waste into
instrumentation: **if calibration looks materially better on 2025 than on 2026,
that gap is the leakage, measured rather than assumed.** It is reported as a
leakage estimate, never as a second result.

### The panel shape, re-derived from Item 2.02 counts

An earlier draft of this analysis sized the panel on "8–12 8-Ks per year". That is
the count across *all* item types — 1.01, 5.02, 7.01, 8.01. The corpus filters to
**Item 2.02, quarterly earnings: four a year at most.** Measured against the real
trading calendar for 2026-01-01 → 2026-08-13:

| quantity | value |
| --- | --- |
| trading days in band | 161 |
| quarter ends reported inside the band | 3 |
| **Item 2.02 filings per ticker** | **2.87** (min 2, max 3) |

Six filings per ticker do not exist in this window, so `40 tickers × 6 dates` is
impossible. The panel is therefore **120 tickers × ~2.87 dates ≈ 344 forecasts**,
which is more than the 240 target and statistically better: near-zero within-ticker
dependence, since almost every ticker contributes a handful of widely separated
dates rather than a run of them.

### Clustering: measured, not assumed

Earnings cluster into reporting season, and the raw counts look alarming:

| measure | value |
| --- | --- |
| distinct calendar dates occupied | **60 of 161** |
| non-empty 5-day blocks | 16 |
| non-empty 10-day blocks | 9 |
| **non-empty 21-day blocks** | **6** |
| forecasts per calendar month | 62, 58, **0**, 61, 59, **0**, 34, 70 |

March and June are empty. But the raw cluster count overstates the damage, because
**a reporting season is not a date**: filings stagger across roughly twenty trading
days as companies report in sector order, and 5-day windows on different days
within one season overlap only partially.

The honest measure is the design effect — the sampling variance of the estimator
under the real date structure against the same N spread uniformly. Measured:

| date structure | design effect | N_eff of 344 |
| --- | --- | --- |
| **realistic earnings dates (60 dates)** | **1.21–1.30×** | **265–285** |
| forced onto 8 dates | 2.05× | 168 |
| forced onto 3 dates — one per season | 5.83× | 59 |

The stress cases are the validation: a measurement that could not detect clustering
would have returned ≈1.0 for all three. It does not, so the benign realistic figure
is a property of the panel rather than of a broken instrument. **Clustering costs
roughly 20–30% of the sample and does not break the design.**

This depended on fixing the block bootstrap first: it drew block starts uniformly
across the calendar and silently discarded empty draws, which with 101 of 161 days
empty left a resample far smaller than the sample. That is the same defect that
made the ADR 0015 calendar-span experiment unusable.

### The regime confound, and why widening buys less than it appears to

Measured on real AAPL, realised volatility over sub-windows as a ratio `r` to the
full sample:

| window | sd(log r) | non-overlapping windows in a 2-year sample | usable |
| --- | --- | --- | --- |
| 4 months | **0.288** | 6.0 | yes |
| 8 months | 0.229 | 3.0 | understates |
| 12 months | 0.149 | 2.0 | no |
| 20 months | 0.019 | 1.2 | **no — discard** |

The 20-month figure is an artefact: in 24 months of data every 20-month window is
~85% the same data, so it measures nothing. Extrapolating 1/√width from the only
credible anchor gives ≈0.20 at eight months and ≈0.13 at twenty, so **widening the
band cuts the regime error bar by about 1.6×, not the 12× the raw table suggests.**

**That extrapolation is conservative in the direction that supports the decision.**
Volatility has long memory, so true scaling decays more slowly than 1/√width and
widening buys even less than 1.6×.

Where it bites: a forecaster with true ratio `k` measured in a band whose realised
vol is `r`× the long run reads `k/r`. At **k = 0.2** — the five-times overconfidence
the first live run actually produced — a ±20% regime factor gives [0.16, 0.25],
still grossly overconfident, and the verdict survives. At k = 0.8 or 1.25 the regime
factor swamps the effect **and** power is only ~32% regardless. The regime confound
and the power ceiling bite in the same place, so widening rescues nothing that was
otherwise rescuable.

## Consequences

- **The primary result is calibration on the clean band**, at 120 × ~2.87 ≈ 344
  forecasts. Power: 100% at k=0.2, 93–98% at k=0.5, ~32% at k=0.8.
- **The band's measured `r` is reported alongside the result as a stated
  adjustment**, not as an error bar. The realised volatility of the band is
  observable after the fact, so the regime factor is a known quantity rather than
  an unknown one, and a reader can undo it.
- **The ambiguous band is run with the identical design**, and the difference
  between the two is reported as a leakage estimate. It is never a second result.
- **Every forecast in this corpus is an earnings-window forecast, and that changes
  what "calibrated" means.** Item 2.02 windows open on an earnings release, so
  realised volatility is far above the 25% unconditional baseline the power figures
  assume: an earnings jump with 5% standard deviation raises the 5-day dispersion
  from 3.52% to 6.12%, an implied annual 43%. This is handled by **splitting the
  claim in two**, reported separately and never merged:

  - **Absolute calibration**, scoped explicitly to earnings windows. A model
    stating unconditional volatility reads as k ≈ 0.58 — decisively detectable —
    but the finding is *"does not widen its interval for earnings"*, not generic
    overconfidence, and must be worded as such.
  - **Relative calibration against the baselines on the same windows.** The
    confound **largely cancels in the paired comparison**: the random walk and
    GARCH also run on unconditional or trailing volatility and also fail to widen
    for a scheduled event, so both sides carry the same handicap and the paired
    difference isolates what is actually different about M.A.P. This is the
    confound-robust comparison and the more interesting of the two.

- **A third baseline is added: trailing realised volatility scaled by an
  earnings-day multiplier.** It costs no inference. Its purpose is to be the
  benchmark that *does* widen, which converts the confound into the measurement:
  if M.A.P. loses to it, the finding sharpens from "miscalibrated on earnings
  windows" to **"fails to widen for a scheduled event that a two-line heuristic
  handles"** — a more useful result than either absolute number.

  **The multiplier is derived from data, never assumed.** The 5% figure above is
  illustrative arithmetic and is not used. The estimator is the ratio of realised
  dispersion in earnings windows to the same ticker's non-earnings windows,
  computed per ticker over the pre-corpus history and applied out of sample.
  Item 2.02 filing dates *are* the earnings dates, so the corpus builder already
  fetches everything the estimator needs — no extra source, and the multiplier is
  fit on history strictly before the forecast window it is applied to.
- Power figures in ADR 0015 assume σ from a 25% annual vol. They are recomputed at
  earnings-window volatility before the primary result is quoted.
- Option 3 (a second item type) stays available and unused. If the clean band ever
  proves too thin, it is the next move, with difficulty recorded as a covariate.

## Open — the boundary itself is still one signal

Everything above concerns the *shape* of the corpus and holds wherever the boundary
sits. **Where the boundary sits is still unconfirmed.** The hedge curve says ~2025H1
and the recall curve has not yet corroborated it, so the band edges in this ADR
inherit that uncertainty. Construction does not begin until it is resolved.

Three instruments have now failed on `gemma-4-12b-qat`, each differently:

| instrument | outcome |
| --- | --- |
| hedge rate | worked — the only usable curve |
| yes/no recall | **degenerate**: answered NO to 24 of 24, scoring exactly the 50% a constant responder scores |
| two-alternative forced choice | **unaffordable**: reasons past 12,000 tokens without answering, ~8 min per item and no result |

Constrained decoding does not rescue the third: the grammar binds the content
channel, but the model reasons first and `reasoning_content` is unconstrained, so
it exhausts a 300-token budget before emitting a single letter.

The yes/no failure was also a **reading error on my part**: 50% from a constant-NO
responder is not chance-level knowledge, it is no measurement at all. The
bias-immune statistic is sensitivity, `d' = z(hit rate) − z(false-alarm rate)`,
which is exactly 0 for any constant responder. That requires an **in-knowledge
control period** to be interpretable — if `d'` is 0 even deep inside the training
data, the instrument is dead rather than the knowledge absent. The current run adds
2023H1 and 2023H2 as controls for that reason.

**The consequence is stronger than "underpowered", and ADR 0017 is corrected by
it.** Every accuracy figure in the original analyst recall curve — the 50%, 60%,
20%, 33% readings — is response bias rather than a measurement of recall. Those
numbers were **invalid, not merely noisy**, so the correct statement is not that
the second signal was too weak to confirm the boundary. It is that **the analyst
boundary has never had a second signal at any point.** The hedge curve has been
alone since the beginning.

### Stopping rule — pre-committed, before the results are looked at

Three instruments have failed and probe iteration can absorb unlimited effort, so
the exit is fixed in advance rather than decided while tired:

- **If `d'` is clearly above zero at the 2023H1/H2 controls and the curve has a
  knee** — the instrument works and has found something. That is the convergent
  validity that has been missing. Use it, and set the boundary where the knee is.
- **If `d'` is at or near zero even at the controls** — the instrument is dead, not
  the knowledge absent. **Stop. Do not build a fourth variant.**

On the dead-instrument branch the fallback needs no invention, because it is already
what Option 4 was chosen to tolerate:

1. Place the boundary at the **earliest plausible point**, so that "clean" is
   conservatively small rather than optimistically large.
2. **Widen the ambiguous band** to absorb the uncertainty.
3. Document the split as **single-signal — hedge rate only, with the
   self-reported cutoff as weak and internally contradictory corroboration.**
4. Proceed to construction.

Option 4 tolerates a fuzzy line by design. A boundary that moves only changes how
much lands in the ambiguous band, and because both bands are run with the identical
design, **the leakage estimate survives regardless of where the line is drawn.**
That is precisely why the fuzziness is affordable.
