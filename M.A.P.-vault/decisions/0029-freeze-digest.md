# 0029 — Split the frozen record the same way the code was split

**Status:** accepted · **Date:** 2026-08-31 · **Builds on** [0018](0018-corpus-band-and-panel-shape.md), [0026](0026-forecast-digest.md), [0028](0028-execution-order.md)

## Context

The interleave of [ADR 0028](0028-execution-order.md) does not take effect until the
running process restarts — it computed `plan()` at launch. So does the reasoning-text
recording. Both are inert until then.

But restarting splits the band across freeze **2.3.0** and **2.4.0**, and `map
evaluate` refuses a band spanning two frozen records **with no override**. The
justification for having no override was that two records mean "two items were not
asked the same question."

**That justification does not hold for 2.4.0.** The amendment recorded the execution
order. Every field deciding what a model is asked — models, prompts, contexts,
truncation, the retry, the horizon, the price vintage, the exhibit hashes, membership
— is byte-identical. The version moved for a reason that cannot reach a forecast.

So the guard as written would have refused every band from the restart onward. That is
[[../Findings & Incidents#27]] from the side it bit last time, and it is exactly the
problem [ADR 0026](0026-forecast-digest.md) solved for the commit.

## Decision

**A digest over the forecast-governing subset of the frozen record**, recorded in
every manifest beside the version, and compared instead of the version.

### The split, and why each field lands where it does

**Governing — a difference here means the items were not asked the same question:**

| field | why |
| --- | --- |
| `models` | alias, temperature, budgets, the degeneration penalty |
| `prompts` | template content hashes |
| `context_tokens` | the window, and therefore the document budget |
| `truncation` | what the model was shown of an oversized exhibit |
| `degeneration_retry` | sampling on a retried item |
| `horizon_days` | in the analyst's prompt, and the target being forecast |
| `price_vintage` | the series, and so the spot price the prompt carries |
| `exhibits` | the document hashes; a change is a different document |
| `corpus` | membership — not what any item was asked, but which population the band is drawn from |
| `kv_cache` | a server setting invisible to both the cache key and the model fingerprint, which is why the freeze records it at all |

**Recorded and excluded:** `freeze_version` (the label this replaces), `frozen_on`,
`amended_on`, `amends`, `amendment_reason`, `note`, `changes` (a changelog of a past
edit; current membership is in `corpus`), `context_verification` (evidence the probe
agreed, not a control), `execution` (band order and retry policy — which items run,
not what they are asked), and `execution_order`.

The bias is the same single direction as the code digest: **over-including costs a
visible false refusal; under-including costs an invisible false claim that two items
were asked the same question.** `corpus` is included on exactly that reasoning — it
changes no individual prompt, but two halves of a band drawn from different
populations are not one band.

A test asserts **every field of the real record is classified**, because a field in
neither list is silently excluded — the invisible direction. It found one immediately:
`amends` had fallen through both lists.

### Why `execution_order` is excluded, argued rather than assumed

This is the field the whole change turns on, so the argument is worth stating rather
than asserting.

An item's prompt, sampling, document, model and target are **byte-identical whatever
order it was attempted in** — `as_of` derives from the filing date, the vintage is
pinned, sampling carries a fixed seed, the cache is content-addressed
([ADR 0028](0028-execution-order.md)). No forecast differs.

The seed changes exactly one thing: **which subset survives a halt.** And the contrast
with `corpus` is what settles it. Changing `corpus` changes the *population*; changing
the seed changes which unbiased *sample* of that same population you got. Two random
subsamples of one population are comparable in a way that two populations are not. If
the band completes, the seed has no effect whatsoever — its effect is conditional on a
halt that may never come.

The honest caveat: the clean band is a hybrid, 80 items in date order plus an
interleaved remainder, so its surviving set is not a clean random sample. That is
recorded in `execution_order.clean_band_hybrid` and reported — and refusing on the
seed would not repair it.

## Verified against the real freeze history

Not asserted — computed:

| comparison | versions | digest | governing fields differing |
| --- | --- | --- | --- |
| the execution-order amendment | 2.3.0 → 2.4.0 | **identical** | **none** |
| the degeneration-retry amendment | 2.2.0 → 2.3.0 | differs | `models`, `degeneration_retry` |

The first is the case this exists for. The second is the control: without it the
digest could be one that never fires, which is the failure being avoided rather than a
solution to it.

**All 133 completed items carry one freeze digest** (`941dc7eefda5`), and the record
the restart will write hashes to the same value. The restart does not split the band.

## Amendment, 2026-08-31 — truncation is scoped to the items it applied to

Lowering the token ratio (ADR 0020 addendum) changed the `truncation` field, and the
digest as first written moved for **every** item in the band — though only 18 of 709
exhibits are cut at all, and only 2 completed items were affected.

That is the code digest's file-granularity problem again: a governing field whose
*actual* effect is narrower than the field. The difference here is that the per-item
answer is known exactly — `truncation.applies_to` names the affected accessions, and
the runner knows whether it cut a given document.

So `freeze_digest` takes `truncated`, and excludes the truncation rule when the run's
own document was not cut. **A rule that did not apply cannot have changed what the
model was asked.**

Measured across the real amendment:

| | 2.4.0 → 2.5.0 |
| --- | --- |
| untruncated items | **same digest** — 133 completed items stay in one group |
| truncated items | digest differs — 2 items, exactly BXP 2026-01-28 and FCX 2026-01-22 |

The digest now identifies the re-runs by itself rather than needing them listed in a
commit message.

**The narrowing applies to truncation alone**, and a test asserts every other governing
field still moves both scopes — a field narrowed silently would be the invisible
direction.

## Consequences

- `manifest_version` goes to **1.7.0**; `RunManifest` gains `freeze_digest`.
- The 133 written items were **backfilled** from `git show <commit>:corpus/frozen.json`
  — the same recovery argument as the code digest, since the freeze a run executed
  under is the one committed alongside the code it recorded. Dirty-tree runs stay
  unknown.
- The refusal **names the governing fields that differ**, recovered from git, so the
  decision to re-run is made on evidence rather than on a hash mismatch.
- Grouping is by digest **alone**. A first attempt put the version into the group key,
  which split a group whose governing content was identical — the very failure being
  removed, reintroduced in a display string. The versions are rendered beside the
  digest instead, so a reader can see which labels share content.
- Three labels stay distinct because they are three facts: `predates the digest`
  (backfillable), `predates the field` (no freeze recorded), and a digest.
