# Results, in full

Every figure the README summarises, with its interval and the population it was
measured on. The headline is in the [README](../README.md); this is the working.

---

## Results

The corpus was frozen and committed before any inference ran; the commit order is the
pre-registration. **356 filings from after the models' training cutoff and 353 from
before it**, 120 companies, 8-K Item 2.02 exhibits, a five-session horizon, point-in-time
aligned so the overnight announcement gap falls outside the window.

**701 forecasts completed. 8 failed** — every one an agent generating its full token
budget and emitting no answer. All are named in `notebook/`.

> **Log score is the negative log predictive density: lower is better.** Stated because
> "improved from −0.949 to −1.237" reads as worse to almost every reader.

### Phase 2 — the measurement

Development half, **175 items in 18 date clusters**, cluster-robust intervals throughout.

| | vs random walk | vs GARCH | vs earnings-scaled RW |
| --- | --- | --- | --- |
| CRPS | worse by 5.4% | indistinguishable | indistinguishable |
| Log score | worse by 12.9% | worse by 12.0% | indistinguishable |

**Calibration ratio 0.733, 95% CI [0.637, 0.801].** The interval excludes 1.0, so the
over-confidence is measured rather than suspected. This was the question the phase was
redesigned around after a power analysis showed directional skill was undetectable at
any affordable sample size.

**Directional accuracy 49.7%** (87 of 175). P(up) spans 0.369 to 0.631 with a median of
0.513 — the system does not so much get direction wrong as decline to have a view. All
three baselines set mean zero by construction and score identically, so this is a
comparison against a coin.

**No measurable training-cutoff leakage.** Clean band 0.0318 against ambiguous 0.0335, a
difference of **−0.0017 with an interval from −0.0093 to +0.0060**. Both halves are now
persisted scoring records, so that difference is re-derivable rather than quoted: mean
CRPS **0.03179** on 175 clean/dev items against **0.03348** on 174 ambiguous/dev items is
**−0.00169**, reproducing the published figure from artifacts. The system scores
marginally worse on the filings it might have memorised — the direction that embarrasses
the contamination hypothesis rather than supporting it. This design could have detected
gross memorisation and could not have detected a subtle familiarity effect of a few
percent, and this sentence is the write-up saying so.

**An extra check, not pre-registered.** The same comparison stated as each band's gap to
the random walk: **+5.41% on the clean band against +3.89% on the ambiguous band, a
difference of −1.52% with an interval from −6.98% to +2.96%** — computed today from the
two persisted records on `block_resamples`, 4,000 draws, seed 20260813, ten-day blocks,
each band resampled on its own days because the two hold different items and pairing is
not defined across them. The interval covers zero, so the bands are not distinguishable on
this measure either. Labelled an extra check because nothing registered it in advance: the
registered leakage statistic is the CRPS difference above, and this is the same evidence
re-expressed against a baseline rather than a second test of it.

### Phase 3 — the correction, and the one-shot test

A two-parameter map `z → (z − a) / b`, fitted on the development half only, by minimising
the log score. Form, objective, success condition and predicted failure mode were all
committed before the fit ran.

Fitted: **a = −0.076** (covers zero, as predicted — there was no directional tilt to
remove), **b = 1.331** (excludes 1, so the intervals genuinely needed widening).

**The pre-registered success condition failed on development.** The corrected body came
out over-dispersed, which is the exact failure mode recorded in advance: a scale fitted
to the log score lets a handful of extreme items pull it up and over-widen the ordinary
ones.

The holdout was then spent, once, on **173 items**.

| | corrected | uncorrected | difference |
| --- | --- | --- | --- |
| Log score | **−1.237** | −0.949 | **−0.288 [−0.453, −0.111]** |
| CRPS | **0.0378** | 0.0387 | **−0.0009 [−0.0018, −0.0001]** |

Both intervals exclude zero. **The correction generalises to data the fit never saw.**

Corrected, the calibration ratio moves from 0.592 to 0.788 and the body's dispersion from
1.380 to 1.037, an interval covering 1.0. The tail ratio does not move — 1.175 to 1.183 —
exactly as predicted, because a location-and-scale map cannot change kurtosis.

**Two claims that must not be merged.** The calibration correction generalises out of
sample. The forecasting did not improve: corrected, the system now beats the
earnings-scaled random walk on CRPS, and still loses to GARCH and to the plain random
walk on both rules. *A better-calibrated statement of the same information is not a
better forecast.*

**And the development failure was not refuted.** The condition failed on development by
0.0069 and passed on the holdout — but the two halves are not distinguishable from each
other. The difference in their uncorrected calibration ratios is **+0.100 with an
interval from −0.065 to +0.249**, and the same holds for every dispersion statistic
compared across the split. Two marginal calls landing on opposite sides of 1.0 in samples
a test cannot separate. The defensible statement is that the correction is approximately
right, and whether it slightly over- or under-corrects is unresolved at this sample size.

### What survives of the holdout, and what does not

**The holdout's per-item scores were not persisted and cannot be recovered.** They were
computed once, printed once, and are gone.

That is correct, not an oversight. `map evaluate --split holdout` is refused *before
anything is computed* once the spend is recorded (ADR 0031), and it is recorded — so
there is no re-run that could produce them, and adding one would mean defeating the
guard. A holdout scored twice is not a holdout.

What survives is in `corpus/holdout_spend.jsonl`, which is **tracked**, so its git
history is the record of the single spend:

- the calibration coefficients — `a = −0.0757`, `b = 1.3305`, `form: z → (z − a) / b`
- what it was fitted on, its ADR, and the notes that amended it
- the band, the item count (173), the date, the commit, the freeze version and the
  price vintage

The band-level results are the table above. Everything else — the 173 individual CRPS,
log-score and PIT values — existed only in one terminal session.

**One band-level result is stated, not verifiable.** The comparison against the three
baselines — pre-registered as secondary measure S5, for both the corrected and the
uncorrected forecast — survives only as the sentence in Phase 3 above: better than the
earnings-scaled random walk on CRPS, losing to GARCH and the plain random walk on both
rules. Every other secondary measure has its figures and intervals in the Development
Timeline. S5 has no figure and no interval in any artifact; the sentence does not say
whether "loses" means an interval excluding zero, and two of its twelve comparisons are not
stated at all. The same comparison on the development half is persisted with its intervals,
under `var/corpus/scores/` and in the export. See Findings #57.

Development-half scoring passes *are* persisted, under `var/corpus/scores/`, because dev
is re-scoreable. So the asymmetry in this repository is deliberate: you can re-derive any
development number from an artifact, and no holdout number.

### Registered replications

Two findings developed on the development half were given pre-registered replication
tests on the second band, written before any of its items were scored.

**Cross-sectional volatility compression: replicated**, against both baselines. The
system's volatilities span about half the range a trailing-volatility baseline does — an
attenuation-corrected slope near 0.4 where 1.0 is correct, with every registered
prediction met and the effect monotone across three cut depths. This is the project's
only finding established out of sample.

**Heavier-than-normal tails: partial.** On the 177 ambiguous items scored at the time the
exceedance counts replicated emphatically — 8 past three sigma against 0.48 expected,
16.7×, over six distinct blocks — while the tail ratio's interval reached down to 0.9945
and so missed excluding 1.0 by 0.0055. Registered in advance as a possible split outcome,
with the disagreeing pair named. Recomputed from the pre-registration four weeks later on
the 174 items still persisted, it gives the same verdict under every reading the record
left open: 17.0× against 0.47 expected, and a lower bound of 0.9947. The Student-t
successor it would have triggered stays unadopted. See Findings #61.

### Phase 4 — what a reader can verify without re-running anything

Phase 4 built read paths, not results. None of it is new evidence about forecasting.

**What you can check, and with what.** The Phase 1–3 results above are verifiable from
this repository alone: `corpus/frozen.json` is the pre-registration and its commit order
is the evidence for it, and `corpus/holdout_spend.jsonl` is the record of the single
holdout spend. Evidence rather than proof throughout, where the thing being relied on is
a git timestamp: dates in a repository are writable, and a 2026-09-08 rebase moved some
commit dates in this one. Read author dates, and read the ordering rather than the clock.
Phase 4's *structure* is verifiable from the source and the test suite — that the journal
cannot compute a score, that populations have no pooled accessor, that a scoring record
refuses to be overwritten. Phase 4's *numbers* are not: 779 runs, 701/74/4, 777 closed,
5.34 MB all come from `var/` and `runs/`, which this repository does not ship. Clone it
and `map export --allow-partial` writes 0.09 MB — the corpus and nothing else.

That boundary is the honest claim. A reader can confirm the machinery does what is
described here; only someone with the artifacts can confirm the counts.

**`map export`** writes the whole readable state as flat JSON into `ui/assets/export` — 5.34 MB, of
which 0.77 MB is eager. No server, no dependency. **`map export --check`** re-derives
the identity of all seven inputs and names what has moved since the export was written,
because a copy goes silently behind and a date alone does not make that visible.

**`map runs`** is the run journal: 779 readable runs of 826 directories, each with its
anchor, the three scenarios it produced, and what the price did. Nothing in it computes
across a forecast and its outcome — no error, no return, no hit — and the type offers no
member that could (ADR 0035). 47 directories it cannot read are counted and reported
rather than dropped.

**`corpus_relation`** tells three cases apart that were previously one:

| | runs | what it means |
|---|---|---|
| `ledger_item` | **701** | the ledger maps this run to a frozen corpus item |
| `repeat_of_exhibit` | **74** | the document is a frozen exhibit; the run is not the ledger's run for it — a re-run, a post-band repeat, an ablation replay |
| `outside_corpus` | **4** | the document is not one the corpus froze |
| `unchecked` | **0** | (779, when no frozen record or ledger is supplied) |

The 74 are 10% of the log and were previously indistinguishable from panel items.
Note also that `ledger_item` is **not** a claim that an item was scored: a ledger entry
promises artifacts exist, and no per-item score is persisted for any holdout item.

**Outcomes are retrieved, never stored**, from the pinned 2026-09-05 snapshot — with the
snapshot named, the provider read from the parquet's own metadata, and the retrieval
date. A run's own vintage ends at its anchor and structurally cannot hold its outcome.
Each run gets one of four answers, never an omission: **777 `closed`, 2 `window_open`,
0 `absent_from_snapshot`, 0 `not_requested`**.

**Development scoring passes persist** to `var/corpus/scores/`, write-once per (band,
split, vintage, code digest) — identical content left alone, differing content refused
rather than overwritten. Two records exist today and both are exported: one from a
committed tree and one from a dirty tree that no longer exists. That is the design, not
clutter — a regeneration under changed conditions lands beside its predecessor.

**The holdout has no such record and cannot**, for the reason given above. The export
states that as a fact in its manifest rather than leaving a missing file to be noticed.

The front end is `ui/`, in this repository, and reads that export — four screens over
the real files, with no fixture behind any figure on them.

### Phase 5 — the ablation, and what remains designed

**Four arms were planned; two produced comparable numbers.**

**A − C = 13.6% on CRPS**, interval well clear of zero, on 355 paired items. It is
**descriptive, not causal**, and the design separates none of the three confounds:

1. the **analyst** is removed;
2. the **model** doing the forecasting changes from a 12B to a 4B;
3. the **prompt** changes, necessarily — the frozen structuralist's first rule is to
   copy the estimate numbers from the narrative, and with no analyst there are none,
   so 11 of 25 lines had to change.

Arm D existed to separate (1) from (2) and could not be made to run. So *"the analyst
helps"* is one of three available readings and the experiment cannot say which.

**Arm D was shown infeasible, not declined.** Every failure was the same shape: the 12B
generating its entire budget as reasoning and emitting no answer. The first rejection
was methodological — 12,000 tokens was a cap, not a wall, with 3,610 tokens of headroom
unused. A ten-item probe at **15,000 tokens**, the largest the 16,384 window allows,
registered in advance with both readings fixed: **ten of ten failed**, seven exhausting
the budget and three unable to fit the prompt at all. Given every token the window
physically allows, the model does not finish — so raising the budget is not an option
that was declined, it is an option that does not exist.

**An unpredicted result:** removing the analyst moved **median P(up) from 0.513 to
0.755**. The system becomes markedly more bullish and more opinionated without the
reasoning stage. Nothing in the pre-registration anticipated this, and it is reported as
unpredicted rather than folded into the CRPS story.

**Everything else in the Phase 5 design document is designed and unbuilt.** Of its six
parts, exactly one — A1, the ablation — has been executed. Not built: trailing realised
volatility as an input (A2), prior guidance from the previous 8-K (A3), the horizon
ladder beyond five sessions (B), the long-term head (C), scenario mode (D), and the
surface work including per-forecast caveats and a generated architecture diagram (E).
The document describes intentions; this paragraph exists so a reader does not mistake it
for a record of work done.

---
