# 0019 — Execution protocol for the corpus run

**Status:** accepted · **Date:** 2026-08-13 · **Builds on** [0018](0018-corpus-band-and-panel-shape.md)

## Context

The corpus is 692 forecasts at 500 s each, measured cold on the current
configuration: **96 hours, twelve nights at eight hours.** That is long enough for
three things to go wrong that are cheap to prevent now and expensive to discover on
night eight.

- A twelve-night commitment invites a mid-run decision to shorten it, and any such
  decision that is informed by a result is data-dependent stopping.
- The clean band carries the primary result. A failure at the halfway point that
  left both bands half-finished would leave nothing reportable.
- Warm cache replay is **3 s against 500 s cold, measured** — 167×. That insurance
  holds only while every prompt is byte-identical. A single template re-version
  invalidates every cache key and buys back the full twelve nights.

## Decision

### 1. Freeze at parity, execute in two passes

The corpus is frozen at **full size, 692 forecasts**, and committed before any
inference. The ambiguous band is then executed in **two halves**, with an option to
stop after the first — buying the ten-night outcome without pre-registering a
smaller corpus.

**The continuation decision is made on elapsed time and nothing else.** It is taken
without inspecting any score, any forecast, or any partial leakage estimate.
Pre-registration survives because the corpus was fixed at full size up front; what
the two-pass split adds is an option on *time*, which is not a function of the data.

**Inspecting a result before deciding would convert this into data-dependent
stopping — the exact contamination Phase 2 exists to prevent.** A leakage estimate
that informed its own sample size measures the analyst's patience as much as the
model's memory.

### 2. Peeking is made structurally awkward, not merely discouraged

A rule that depends on remembering it at 1am is not a rule.

- **Scoring is a separate command from running.** The runner writes forecasts and a
  ledger; it computes no scores and prints none.
- **Scoring refuses to run until every pass the corpus declares is marked
  complete.** A partially executed corpus produces an explicit refusal, not a
  partial number.
- The ledger records pass completion; the continuation decision reads only the
  ledger's timing columns, which contain no outcome.

### 3. The clean band runs first, to completion

The clean band carries the primary result, so it is finished before the ambiguous
band is touched. A failure on night eight then leaves a complete primary result and
an unstarted secondary one, rather than two useless halves.

### 4. Prompt freeze, asserted rather than intended

The frozen corpus records, alongside the pinned price vintage:

- every prompt template's **name, version and content hash**
- the model aliases and their fingerprints
- the sampling parameters

**The runner asserts at startup that the live templates match the frozen hashes and
refuses to start on mismatch.** Not a warning — a refusal.

This is the largest operational risk of the next fortnight, and it will not present
itself as a risk. It will present itself as a small sensible improvement to a
prompt at 1am. Restarting a twelve-night run must be a deliberate decision with a
stated cost, never a side effect of editing a file.

### 5. Chart rendering is off, and asserted rather than defaulted

`write_chart` inlines the whole Plotly bundle so a chart is a single self-contained
file. At ~4.5 MB per run that is **3.3 GB of byte-identical JavaScript across 727
forecasts**, for a picture nothing in Phase 2 reads.

Rendering therefore becomes opt-in, and the runner **asserts it is off** rather than
relying on a default. A default is a property of a call site someone can change; an
assertion fails the run. Scoring reads `forecast.json`, never the chart.

### 6. A failure threshold, fixed now rather than on night eight

Per-item retry, then `status=failed` and continue, is right for one item. It is
wrong for fifty: **a corpus with items missing is no longer the corpus frozen at
`36e08a3`**, and the pre-registration claim weakens without anyone deciding that it
should. So the runner halts instead of completing a degraded corpus.

Two thresholds, because scattered bad luck and systematic failure look different:

| trigger | limit | what it catches |
| --- | --- | --- |
| **consecutive failures** | **5** | the inference server down, a provider revoked, disk full — a state that will not fix itself |
| **cumulative failures in a band** | **2%** (≈7 of 365) | slow attrition that would still leave the corpus materially incomplete |

Five consecutive is a strong systematic signal: at any plausible per-item failure
rate, an unbroken run of five is far more likely to be one cause than five
coincidences. The 2% cap keeps any completed band at least 98% of what was frozen.

**Failures are recorded by reason**, so the ledger distinguishes one provider
failing, one band failing, or one ticker failing from genuinely scattered noise.
On halt the runner reports the breakdown and stops; resuming is a deliberate act
after the cause is understood, not a retry loop.

### 7. Health metrics are visible during the run; scores are not

Waiting twelve nights to discover that transcription fidelity collapsed on night two
would waste the run. The runner therefore reports continuously:

- transcription fidelity (unparseable and divergent counts)
- ungrounded-numeral warnings
- degenerate-spread flags
- budget exhaustion and reasoning-token totals
- failures by reason, and the two threshold counters

**None of these is a score**, so none of them touches the two-pass continuation rule
in §1. They describe whether the machine is working, not whether the forecasts are
good. CRPS and everything derived from it stay behind the separate scoring command,
which still refuses to run until every declared pass is complete.

The distinction is the operative one: **"is the pipeline healthy" is an engineering
question and may be watched; "is the forecast any good" is the result and may not.**

## Consequences

- Total: **692 forecasts, 96 hours, twelve nights** — clean 346 (6.0 nights), then
  ambiguous 173 + 173 (3.0 nights each).
- Stopping after the first ambiguous half gives **~10 nights** and costs about 13%
  on the standard error of the leakage difference (ADR 0018 sizing).
- A forced full re-run with prompts unchanged costs **35 minutes**. With any prompt
  changed it costs twelve nights. The asymmetry is the entire reason for §4.
- The runner needs a ledger keyed by `(ticker, band, filing_date)`, appended only
  after every artifact for an item has landed, so an interrupted run resumes at the
  failed item rather than from zero and a half-written run directory is never
  mistaken for a complete one.


## Amendment, 2026-08-15 — the pass boundary, and what the manifest was missing

### Passes interleave; a contiguous half would confound stopping with seasonality

The two-pass split was pre-committed above and enforced nowhere, which is how a
pre-registered rule quietly stops being one. Enforcing it surfaced a flaw in the
design *as originally conceived*, and it is worth stating rather than silently
fixing.

The obvious implementation is to take the first half of the plan as pass one. The
plan is ordered by date, so that half is **calendar-contiguous** — roughly the first
half of the band's year. Stopping after it would then mean the leakage estimate was
computed on H1 alone, and "we stopped early" would be inseparable from "we only
measured spring". Reporting season, earnings seasonality and whatever regime
happened to prevail in those months would all be baked into the headline, with
nothing in the record showing it.

**Passes are therefore assigned by position modulo the pass count**, so each is a
spread sample of the whole band. An early stop costs precision and nothing else,
which is the only thing the continuation rule was ever meant to trade away.

The assignment is a pure function of the frozen plan order — no seed, no stored
mapping, same answer on any machine. `require_finished` takes a `declared` argument
so a deliberate stop after the first half stays distinguishable in the record from a
run that never finished; those are different claims and the ledger must not blur
them. `elapsed_report` exposes wall-clock time and nothing else, which is the only
quantity §1 permits the decision to read.

### The manifest recorded every input except the program

It pinned model fingerprints, prompt hashes, sampling parameters, the price vintage
and the adjustment basis — and said nothing about which code produced the run.

For a twelve-night corpus that is a real gap. A job that dies at item 200 and
resumes executes its second half under whatever commit is checked out then, and a
corpus spanning two commits is an ordinary thing to happen and an indefensible thing
to be unable to see afterwards. Manifests now carry the **commit SHA and a
dirty-tree flag**, and `map evaluate` refuses to score a band produced by more than
one version unless `--allow-mixed-code` is passed, printing the split either way.

A dirty tree is recorded rather than forbidden. Refusing to run on uncommitted
changes would make every experiment need a commit first; saying so honestly is the
better trade.

The lookup is cached for the life of the process, deliberately: committing while a
run is in flight changes what `git rev-parse` answers but not the code already
imported and executing, so the cached first answer is the accurate one.

### What this does not fix, stated rather than left silent

**The clean-band run currently in flight began before this field existed.** Its
manifests carry no commit, and `map evaluate` reports them as
`unknown (predates the field)` rather than inferring one.

That inference would be easy and wrong. The commit could be guessed from the run's
timestamp against the git log, and the guess would be right most of the time and
unfalsifiable when it was not — a plausible number in place of a missing one, which
is the failure mode this project spends most of its effort on. The same principle
applies here as to the `STATE.md` entry left unrewritten during the vault migration:
**a record says what was true, and is not retrofitted to what we wish had been
recorded.**

The field is therefore fully populated only from the ambiguous band onward, and any
report covering the clean band must say so.


## Pre-commitment, 2026-08-15 — the ambiguous band runs at full parity

**Decided now, and recorded now, specifically because no score exists anywhere yet.**
The clean band is still executing, nothing has been evaluated, and the scoring pass
had not been written when this was written. There is therefore no number that could
have influenced this decision, and the commit ordering in this repository is the
evidence for that rather than an assurance.

**The ambiguous band will run both passes at full parity. It is not a decision to be
taken later on elapsed time.** §1 created a continuation option; this spends it, in
advance, in the only direction that does not depend on data.

### Why parity rather than stopping at half

The sizing work in ADR 0018 put the knee at parity: moving from 0.5× to 1.0× buys
11.8% off the standard error of the leakage difference, while 1.0× to 1.5× buys only
4.1% for the same 2.2 nights. Parity is where the return stops being worth the time.

More decisive is what the leakage estimate is *for*. **It is the entire justification
for restricting the primary result to the clean band.** ADR 0018 chose Option 4 —
clean band primary, ambiguous band as instrumentation — on the argument that leakage
biases calibration in the flattering direction. If the leakage number is itself soft,
that restriction is unsupported: we would have paid the cost of a narrow clean band
without the measurement that justifies paying it. A weak leakage estimate is the one
economy that undermines the design it was economising within.

### The consequence, which is the point

Because the ambiguous plan is now fixed and unconditional, **scoring the clean band
the moment it finishes cannot contaminate anything.** There is no remaining decision
for a clean-band score to influence: not which items run, not how many, not for how
long. The sequence becomes:

> clean band → **score the clean band** → ambiguous band runs regardless → leakage estimate

That is roughly six days earlier for the primary result, at no methodological cost.
The cost was avoided by giving up the option in advance rather than by reasoning
carefully about it afterwards, which is the only reliable way to give up an option.

The residual risk is not statistical but human: seeing a clean-band score and then
adjusting the ambiguous run. The structural guards already cover it — the corpus is
frozen and committed, and the runner refuses to start if a prompt template or model
alias differs from the frozen record (§4). Changing the ambiguous run after seeing a
score would require amending the freeze, which is a visible, dated, deliberate act.

### In code

`map evaluate --band ambiguous` is run with both passes declared:

    --declared ambiguous_half_1,ambiguous_half_2

which is also the default `require_finished` behaviour when `declared` is omitted.
It is passed explicitly all the same, so the record shows a declaration that was
made rather than a default that happened to apply.

---

## §8 — The band launches from a clean tree, added 2026-08-31

**The rule.** A band is launched from a committed working tree, and **no commits are
made while it runs.** If a defect emerges that genuinely requires a code change, the
run is **stopped**, the change is committed, and the run resumes. Every item then
carries a forecast digest that proves what produced it.

**Why it is enforced rather than intended.** 33 items of the clean band were produced
from an uncommitted tree, because development continued against a live run. A dirty
tree records `code_version.dirty` and **no forecast digest** — the commit does not
describe the files that executed — so those items can never be shown equivalent to any
other item. They form a stratum of their own, permanently.

The clean band could absorb that: 33 of 356 is 9%, and their freeze digest was
recoverable, so they remain scoreable under `--allow-mixed-code`. **The ambiguous band
is 353 items and the leakage estimate is a difference between the two bands** — a 9%
unprovable stratum on one side of that comparison is a different proposition from a 9%
stratum inside one band's own result.

**This was already the instruction and neither of us held to it.** A rule enforced by
intention is the kind that gets broken by the person who wrote it, in the moment when
breaking it is convenient — which is exactly when it matters. So `map corpus run`
refuses to start on an uncommitted tree.

**`--allow-dirty` exists**, and for the reason the determinism override exists (ADR
0007): a hard block with no way through invites someone in a hurry to delete the check,
which leaves no trace at all. The override is loud, says what it costs, and marks every
item the run produces.
