# 0033 — Phase 3's outcome against its pre-registration

**Status:** accepted · **Date:** 2026-09-05 · **Written after the holdout was spent** · **Records the outcome of** [0032](0032-calibration-form.md), amended by git note records 3 and 7 · **Builds on** [0031](0031-holdout-spend.md), [0003](0003-price-adjustment-semantics.md)

## Why this ADR exists

[ADR 0032](0032-calibration-form.md) pre-registered the correction before anything
was fitted. This one records what happened, item by item, **against what that
document said would happen** — so the phase can be read without reconstructing it
from the git notes, and so the places where the pre-registration was silent or
incomplete are visible rather than inferred.

> **Log score convention.** Lower is better throughout: the score is the negative
> log predictive density. −1.237 is better than −0.949.

## What was pre-registered, and what happened

| pre-registered | outcome |
| --- | --- |
| form `z -> (z - a) / b`, two parameters | held |
| both fitted on development only | held — 175 items, closed form under the log-score objective |
| objective the log score, **not** the calibration ratio | held |
| `a` expected near zero | **−0.0757**, CI [−0.4426, +0.1880] covering 0 |
| success condition: corrected MAD-scale consistent with 1.0 | **FAILED** on the refitted reading, [0.6997, 0.9931] |
| tail ratio predicted unchanged | held — 1.2267 → 1.2247 |
| Student-t adopted **iff** the tail excess replicates on the ambiguous band | **not adopted** — replication was PARTIAL and stayed PARTIAL |
| holdout reported once | held — 173 items, spend recorded in `corpus/holdout_spend.jsonl` |

## The result

**The correction generalises.** On 173 holdout items over 22 clusters, with `a` and
`b` fixed and no refit:

| | corrected | uncorrected | difference |
| --- | --- | --- | --- |
| log score | **−1.23725** | −0.94947 | **−0.28778 [−0.45255, −0.11117]** |
| CRPS | **0.03782** | 0.03873 | **−0.00090 [−0.00178, −0.00012]** |

Both intervals exclude zero in favour of the corrected forecast.

**The forecasting did not improve.** Corrected, the system beats the
earnings-scaled random walk on CRPS — up from indistinguishable — and still loses
to GARCH and the plain random walk on both rules. A better-calibrated statement of
the same information is not a better forecast, and the two claims are kept apart
wherever this phase is reported.

## Three places the pre-registration was incomplete

**1 · The success condition did not specify its estimator.** Record 3 said
"cluster-robust 95% CI from the same moving-block bootstrap" without saying whether
`a` and `b` are refitted inside each resample. Refitted it fails by 0.0019; held
fixed it passes. Both estimands are legitimate and answer different questions — the
fixed reading describes what the holdout actually does, the refitted one asks
whether the procedure calibrates on a fresh sample. **Called FAIL on the refitted
reading**, and recorded as a judgement the pre-registration should have removed.
This is the second such gap: ADR 0032's original A² condition cited the iid 2.492
point for an 18-cluster panel. Rule now recorded: *a threshold is not a
pre-registration unless the estimator is also pre-registered.*

**2 · Nothing said whether a failed condition still spends the holdout.** ADR
0032's only sentence about sequencing is unconditional; record 3 defines FAILS and
stops. So the decision could not be made from the record, and **Kamil made it
having seen the failed fit** — recorded as such in git note record 12. The
reasoning: declining would condition the holdout on a development result, which is
the selection the holdout exists to prevent.

**3 · The holdout does not adjudicate the development condition.** The condition
failed on development and passed on the holdout, and the two halves are **not
distinguishable from each other** — the corrected MAD-scale difference is −0.1236
[−0.4343, +0.1014]. Two marginal calls either side of 1.0 in samples a test cannot
separate ([[Findings & Incidents]] #49). No claim is made that the holdout refuted
the development failure.

## Consequences

- Phase 3 is complete. **The holdout is spent and cannot be reused**;
  `corpus/holdout_spend.jsonl` names the fitted `a` and `b` rather than `null`.
- The predicted inadequacy held exactly: a shift and a scale did not move the tail
  ratio, and the exceedance counts fell only as far as rescaling moved the
  threshold. **This was pre-registered as a prediction, so it is confirmation
  rather than a shortfall.**
- **Student-t is not adopted**, and the reason is its trigger rather than this
  phase's numbers: replication on the ambiguous band was partial. That band remains
  unused for calibration and is still available to test a per-item volatility map.
- Scoring is pinned to the **2026-09-05 snapshot**, 701 of 701 windows — the first
  complete single-vintage snapshot in the project. Three SCCO items are a
  `SpotDriftError` stratum; dropping them is conservative rather than correct, and
  split-aware drift handling is on the Phase 5 list.
