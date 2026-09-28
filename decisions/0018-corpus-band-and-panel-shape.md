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

### Budget exhaustion is non-random missingness, and it is worst at the knee

The analyst deliberates longest on what it cannot retrieve, so items lost to
`ModelBudgetExhaustedError` are preferentially the ones it is least certain about.
Dropping them leaves the confident items and **biases `d'` upward**, and it does so
hardest in the post-cutoff periods — exactly where the knee would be read.

Two mitigations, neither of which requires trusting a caveat:

1. **`d'` is reported as bounds, never as a point estimate.** Once with exhausted
   items dropped, once with them coded as discrimination failures — a miss on
   signal trials, a false alarm on noise trials. The truth lies inside that
   interval. **A knee that survives both readings is real; a knee that appears only
   under the dropped reading was manufactured by the missingness.**
2. **Deliberation length is a fourth signal, and it is free.** `reasoning_tokens`
   is already recorded per item. If the model thinks longer about what it cannot
   retrieve, deliberation length by period is itself a boundary curve — and it is
   **immune to this bias, because an exhausted item is not missing data but the
   maximal observation**, censored at the budget rather than absent. That gives
   four signals in total: hedge rate, `d'`, self-report, and deliberation length.

The confound becomes the measurement, the same move as the earnings baseline.

### Contingency, held in reserve — do not switch mid-run

Gemma 4 has configurable thinking, and for a *recall* probe deliberation is
arguably irrelevant: either the model holds the fact or it does not. Suppressing
thinking would remove exhaustion entirely and cut ~347 s/item to seconds.

**If the exhaustion rate climbs materially in the post-cutoff periods, that is the
fix — not another round of discounting.** It is recorded here so it is not
reinvented under pressure. It must not be switched on mid-run: it changes the
instrument, so any comparison would be across two different instruments, and the
run would have to restart from the controls.

## Outcome — the rule fired on the dead branch

**The controls came back dead, and the fallback is in force.**

| period | n | exhausted | YES answers | d′ dropped | d′ coded | interval | bias c |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2023H1 (control) | 24 | 8% | **0 of 22** | −0.08 | −0.90 | **[−0.90, −0.08]** | 1.73 |
| 2023H2 (control) | 24 | 8% | **0 of 22** | −0.08 | −0.90 | **[−0.90, −0.08]** | 1.73 |

Both control periods sit deep inside the training data of every model in the
registry. **The analyst said YES to 0 of 44 usable control items**, including
events it must have seen. `d'` is at or below zero under both codings and its
worst-case 95% lower bound is −2.78. The response bias `c = 1.73` is extreme.

This is not a model that has forgotten 2023. It is an instrument that cannot
measure recall in this model at all, because the model will not answer YES to a
dated factual question regardless of whether the event happened. **Per the
pre-committed rule: stopped, and no fourth variant built.**

The bounded reading earned its place immediately — the two codings differ by 0.82,
which is larger than either estimate, so a point estimate here would have carried
false precision in a case where nothing was measured.

### The fallback, applied

1. **Ambiguity starts at the earliest plausible cutoff, 2025H1** — where the hedge
   curve first lifts off zero.
2. **The ambiguous band widens to 2025H1–2025H2**, absorbing the uncertainty.
3. **Clean band: 2026H1 onward**, 161 trading days, resting on **the hedge curve
   alone** with the self-reported cutoff as weak and internally contradictory
   corroboration. Documented as single-signal wherever it is reported.
4. Construction proceeds on that basis.

Option 4 is what makes this affordable: both bands run with the identical design,
so **the leakage estimate survives wherever the line falls.**

### The fourth curve is still accumulating

The deliberation curve is unaffected by the dead instrument — it does not depend on
the model answering correctly, only on how long it thinks — so the run continues
purely to collect it. Controls read **median 382 and 338 reasoning tokens** with
heavy right tails (means 1381 and 1374, ~8% censored at the budget). If the median
climbs materially past 2025H1 while the controls sit near 350, that is a second
signal obtained for free; if it stays flat, the split remains single-signal and is
reported as such. **It is a bonus, not a blocker: construction does not wait on it.**


## Constructed — measured shape, and the corrections it forced

**120 tickers, 727 forecasts, dev/holdout 60/60.** Ordering digest
`3164a783e8d48581…`; frozen in `corpus/frozen.json`.

| band | forecasts | per ticker | distinct dates | 21d blocks | 5d blocks |
| --- | --- | --- | --- | --- | --- |
| clean | 365 | 3.04 | 94 | 11 | 39 |
| ambiguous | 362 | 3.02 | 116 | 17 | 55 |

Attrition over 1,161 examined: **illiquid 705 (60.7%), no_price_history 318
(27.4%), too_few_filings 18 (1.6%), accepted 120 (10.3%)**. Liquidity is the entire
binding constraint — the filings requirement passed 100% of liquid names in the
first 250 and rejected only 1.6% overall, so the projection that filings would
halve the yield was wrong.

### The screen is uncontaminated, and it used one provider

All 1,161 candidates were screened through `YFinanceProvider` directly rather than
the failover chain, so **no provider mixing occurred and the pre-registered floor
means one thing by construction.** Stooq could not have served in any case: its CSV
endpoint now sits behind a JavaScript proof-of-work challenge, so the ADR 0003
fallback is currently dead — recorded here because a single unofficial scraper is
now a single point of failure for the whole project, not just for this walk.

Volume needed checking, because price is normalised to split-adjusted and **volume
is not normalised anywhere**. Measured across NVDA's 10:1 June 2024 split, yfinance
adjusts both consistently: median close $85.93 pre-split (from ~$860) against
volume 477M (from ~48M), same factor, and dollar volume continuous across the split
at a ratio of 1.14 — ordinary activity difference, not a factor-of-ten artefact.

A throttled fetch and a dead ticker both surface as `no_price_history`, so
throttling could have silently rejected live names. It did not: the rate is flat
across every hundred-candidate bucket (18–34%, no late-session spike) and **0 of 40
re-probed names fetch successfully now.**

### What `no_price_history` is — and the survivorship question

Re-probing a sample of 40: **78% unknown to the price provider, 22% listed late in
the window, 0% throttled.** At least 15 of the 318 are preferred shares, warrants
or units (`MS-PQ`, `NEE-PN`, `PCG-PI`), which the SEC ticker file lists and the
price provider names differently. This bucket is therefore **mostly non-common
securities and notation mismatches, not dead companies** — benign for composition.

The real survivorship exposure is elsewhere and is structural: **the universe comes
from a current SEC ticker file, so both bands are conditioned on survival to August
2026.** A company that failed during 2025 is absent from the ambiguous band. Because
the headline is a difference and both bands hold *the same tickers*, the bias
applies identically to each side and largely cancels — the same-ticker constraint
earning its place a second time. It is recorded rather than corrected, and any
absolute (non-differenced) statement about the ambiguous band must carry it.

### Power, recomputed on the corpus's own volatility

The screened universe is **29.6% median realised volatility, not the 25% assumed**,
and dispersed: p25 23.2%, p75 42.1%, max 147.6%. The level is nearly irrelevant —
CRPS scales with σ, so signal and noise scale together — but the **heterogeneity
does not cancel**, and it moves power asymmetrically:

| k | homogeneous 25% | empirical | p90-capped |
| --- | --- | --- | --- |
| 0.2 | 100% | **100%** | 100% |
| 0.5 | 100% | **100%** | 100% |
| 0.8 | 66% | **96%** | 89% |
| 1.25 | 74% | **11%** | 24% |

Heterogeneity makes over-confidence *easier* to detect and over-dispersion *harder*:
high-volatility tickers produce large `|y|`, which punishes a too-narrow interval
severely, while a too-wide one is partly correct for those same names.

**The over-dispersion branch is therefore reported as underpowered at 11%.** A null
there means nothing about the world (ADR 0015's rule), and it must never be read as
"the forecaster is not too wide".

**The p90 volatility cap is rejected**, and not merely because it buys the k=1.25
branch back to only 24%. Capping the universe by realised volatility would be
**selection on the dependent variable**: volatility is the quantity the calibration
result is about, so trimming the sample by it tunes the corpus on the outcome
distribution and makes the headline partly an artefact of where the cap was placed.

### The relevant k, on current evidence

The earlier justification cited the first live run's `k ≈ 0.2`, which came from the
units-bug era and has no standing. **The v3 template states vol 0.20–0.22**, and the
earnings multiplier is now measured rather than assumed — **1.28×**, from the
corpus's own filing dates (earnings windows annualise to 55.3% pooled against 43.3%
for all other windows).

| denominator | k | power |
| --- | --- | --- |
| unconditional, median ticker (29.6%) | **0.71** | 96–100% |
| earnings-window, median ticker (37.9%) | **0.55** | 100% |
| earnings-window, pooled (55.3%) | 0.38 | wrong statistic — pooled is inflated by the skewed tail |

**The power table uses the unconditional median, which is the conservative choice:**
the simulation generates returns at 29.6% while real earnings windows run 1.28×
hotter, so realised detectability is at least what the table reports.


## Amendment, 2026-08-15 — applying the replacement rule, not changing it

The pre-flight exhibit fetch found that **30 of 727 items had no usable Exhibit 99.1**, concentrated
in a handful of filers, and that both bands therefore exceeded the 2% failure allowance in ADR 0019.
Left alone, the run would have halted during night one.

**This is the pre-registered replacement rule being applied, not a new rule.** Whether a company
attaches its earnings release as EX-99.1 is a deterministic property of how that company files —
identical every quarter, identical in both bands. It is a selection criterion that should have been
screened at selection; discovering it late makes it a *missed* criterion, not a new one. Tickers
failing it are dropped and replaced by the next names in the seeded ordering, exactly as `no_cik` or
`illiquid` names always were. **Replacements must clear every criterion including the exhibit check**,
or a failing ticker is simply replaced by another failing ticker.

A second criterion was added for the same reason: **CIK uniqueness**. `BRK-A` and `BRK-B` are two
listings of one company filing one 8-K with one exhibit, so the corpus held the same document twice
and counted it as two independent observations — three duplicate exhibit hashes made it visible. This
is general rather than a Berkshire patch: `GOOGL`/`GOOG` and `FOXA`/`FOX` would behave identically.
**The class kept is whichever the seeded ordering reached first.** "Larger", "cheaper" or "more
liquid" would all be judgement calls, and judgement in selection is precisely what pre-registration
exists to remove.

| | before | after |
| --- | --- | --- |
| tickers | 120 | 120 |
| forecasts | 727 | **709** |
| dropped | — | `BRK-A` (duplicate CIK), `GEN` (no EX-99.1 on any filing) |
| added | — | `CG`, `WULF` |
| exhibits verified | 0 | **709 of 709** |

Re-verified end to end: **every item in the amended corpus fetches its exhibit, with zero attrition.**

**The amendment precedes all inference.** No forecast has been produced, so no result could have
influenced which tickers were dropped. Commit `36e08a3` is retained in history rather than rewritten —
the pair of commits is more auditable than a single clean freeze, because it shows what was known when.

The frozen record now also carries the two things it was missing: **accession numbers** for every item,
and the **content hash of every exhibit**. Until this amendment there were no per-item hashes at all,
only prompt-template and ticker-ordering digests, so the claim that the corpus is "a list of
identifiers plus content hashes" was not yet true. It is now.
