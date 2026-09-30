# 0032 — Pre-registering the Phase 3 correction: a two-parameter map, fitted on development only

**Status:** accepted · **Date:** 2026-09-02 · **Written before any correction was fitted, and while the holdout is unspent** · **Builds on** [0018](0018-calibration-target.md), [0031](0031-holdout-spend.md)

## Context

The development half is scored. 178 items, 18 date clusters, and the dispersion result
is this:

| statistic | value | reading |
| --- | --- | --- |
| calibration ratio | 0.733 [0.637, 0.798] | under-dispersed, interval excludes 1.0 |
| mean PIT vs 0.5 | 0.4893 [0.4098, 0.5423] items, [0.3964, 0.5371] clusters | **no tilt** |
| KS *D* vs uniform | 0.0726 (p=0.291 under independence) | no departure |
| Anderson–Darling *A²* | **3.044** vs 2.492 at 5% | **departs** |

Phase 3 has to commit to the *form* of the correction before fitting one, because the
form is a researcher degree of freedom exactly like the threshold and the exclusion set
were. A form chosen after seeing which form fits best is not a correction, it is a curve
through the development set.

## Options

**1. A scale factor alone**, `sigma -> c * sigma`. The obvious reading of a 0.733 ratio.
Rejected as the sole form: with only one parameter there is nothing to absorb a location
error, so if one appears in the holdout it would be silently loaded onto `c`.

**2. A two-parameter location-and-scale map**, `z -> (z - a) / b`, so the corrected
forecast is `mean + a*sigma` with dispersion `b*sigma`. **Chosen.**

**3. A full quantile map** (isotonic, as [ADR 0018](0018-calibration-target.md)
originally sketched). Rejected for now: it has as many effective parameters as the panel
has distinct outcomes, and 18 clusters cannot support it. It stays available for a later
corpus and is named here so that adopting it later is a visible change of plan.

## Decision

**`z -> (z - a) / b`. Two parameters, `a` a location shift and `b` a scale factor, both
fitted on the development half and nothing else.**

### The form was chosen after seeing the development PIT, and that is legitimate here

Stated plainly because it is the kind of thing that is usually buried. The table above is
development evidence, it was looked at, and it is why the form has two parameters rather
than five or one.

**This is legitimate for exactly one reason: the holdout is unspent, and there is a
committed record proving it** ([ADR 0031](0031-holdout-spend.md)). Choosing a model form
on one sample and testing it on another that has never been examined is ordinary
practice. What makes the claim checkable rather than asserted is that this ADR is
committed *before* any correction is fitted, and the holdout's untouched state is a
verifiable fact about the repository rather than a memory. The git history is the
pre-registration, the same way the frozen corpus commit is the pre-registration of the
sample.

### `a` is not motivated by the development evidence, and is included anyway

The tilt is **not established** — both intervals cover 0.5 comfortably. So the honest
expectation is `a ≈ 0`.

It is in the form regardless, and deliberately. If `a` were left out now and the holdout
later showed a location error, adding it at that point would be a parameter chosen after
seeing the holdout, which is the one thing the holdout exists to prevent. Carrying a
parameter the development data says is unnecessary costs a little power and buys the
guarantee that the form does not move. **`a` fitting to near zero is a result, not a
wasted parameter.**

### The fitting objective is the log score, NOT the calibration ratio

This is the substantive constraint, and it comes from a disagreement between the two
dispersion statistics that had to be resolved before anything could be fitted.

The ratio says 0.733. The PIT says uniform-in-the-body. Both are right, because they
weight outcomes differently — the ratio is a quotient of root-mean-squares and is
dominated by the largest moves, while the PIT is rank-based and barely notices them:

| | value | calibrated value |
| --- | --- | --- |
| MAD-based scale of `z` | 1.079 | 1.0 |
| median &#124;z&#124; | 0.7445 | 0.674 |
| RMS `z` | **1.324** | 1.0 |

The body is calibrated to slightly wide; the aggregate is far too narrow. **The top five
outcomes carry 28.5% of the sum of squared returns**, and dropping them moves the ratio
from 0.733 to 0.843.

So a scale factor fitted on the RMS ratio would multiply every sigma by about 1.36 to
accommodate five events, leaving the other 173 items badly over-dispersed — a correction
that makes the log score and the PIT worse while making the headline ratio look perfect.
`b` is therefore fitted by **minimising the development log score**, which weighs every
item once and is the rule that punishes a wrongly-placed tail.

## Amendment, 2026-09-05 — the figures above are the evidence this decision rested on

**Every number in this ADR is the 178-item development half on the 2026-09-02 price
vintage, and none of it is edited.** An ADR records what was believed when the decision
was made; overwriting it would destroy the only evidence that the reasoning matched the
evidence available at the time.

Three events moved the corpus afterwards: six stale-truncation re-runs, three SCCO items
excluded by `SpotDriftError` after a split the provider applied 25 days late, and a
re-derivation onto one pinned 2026-09-05 snapshot. On that basis the development half is
**175 items**, and the dispersion table above reads MAD-scale 1.0864, RMS `z` 1.3242 and
tail ratio 1.2267.

**None of it changes the decision.** The form, the objective, the argument for the log
score over the calibration ratio, and the expectation that `a` fits near zero all survive
the re-derivation unchanged. See [[0033-phase-3-outcome]] for the current figures and the
outcome.

## Consequences

- Phase 3 fits `a` and `b` on the development half by minimising its log score, then
  reports the holdout once, under [ADR 0031](0031-holdout-spend.md).
- **The form is known to be inadequate in a stated way, and this is the pre-registered
  test of that.** A location-scale map cannot fix excess kurtosis, and the A² result says
  the residual is kurtosis. So: *if the corrected development PIT still has A² above
  2.492, the two-parameter form has not fixed the shape, and that is to be reported as a
  negative result rather than patched with a third parameter.* Written down now so the
  outcome cannot be reinterpreted later.
- The tails are the open question either way, and no correction of this family addresses
  them. A heavier-tailed predictive distribution — Student-t on the simulated returns
  rather than the normal the PIT and log score currently assume — is the natural next
  form, and it is named here so that reaching for it later is a recorded change of plan
  rather than a quiet improvement.

## Erratum, 2026-09-30 — two links to a file that never existed

Both links above to ADR 0018 point at `0018-calibration-target.md`. No file of that name
has ever existed in this repository; ADR 0018 has always been
[`0018-corpus-band-and-panel-shape.md`](0018-corpus-band-and-panel-shape.md), under
`docs/decisions/`, then `M.A.P.-vault/decisions/`, then `decisions/`. That is the file the
**Builds on** line means: it makes calibration on the clean band the primary result.

The second link also says the isotonic quantile map was "as ADR 0018 originally
sketched". ADR 0018 does not mention isotonic regression. The sketch is in
[ADR 0015](0015-what-the-corpus-can-actually-answer.md) ("fix it in Phase 3 with
isotonic regression") and in `CLAUDE.md` §8's Phase 3 plan.

The links are left as they were written. Nothing in the decision depends on them.
