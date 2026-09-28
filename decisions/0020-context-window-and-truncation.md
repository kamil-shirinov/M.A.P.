# 0020 — Context windows, and the truncation rule for oversized exhibits

**Status:** accepted · **Date:** 2026-08-15 · **Builds on** [0018](0018-corpus-band-and-panel-shape.md), [0019](0019-corpus-execution-protocol.md)

## Context

The first clean-band run halted after nine failures in its first hour. Every one
had the same cause: an 8,192-token context window. Eight said so in the response
body; the ninth, TSLA, reported budget exhaustion after 6,699 reasoning tokens —
the same defect wearing a different name, because the analyst's 12,000-token budget
could never fit an 8,192-token window and the model stopped at the context ceiling.

**Nothing had ever measured document size against context capacity.** Every test
ran against a 470-character synthetic news file. Real Item 2.02 exhibits are three
orders of magnitude larger.

Measured across all 709 frozen exhibits:

| | chars | ≈ tokens |
| --- | --- | --- |
| min | 652 | 190 |
| median | **31,751** | **9,070** |
| p90 | 51,188 | 14,600 |
| max | 219,441 | 62,700 |

**The median exhibit did not fit.** At 8,192 the run was going to fail on 54% of
the corpus; it was not unlucky.

Token estimates are calibrated against real rejections rather than assumed: the
server reported 13,830 tokens for ALLY's 51,188 characters (3.70 chars/token) and
roughly 33,000 for FCX's 131,879 (4.00). TEL fitted at 29,216 characters and FAST
did not at 32,295, which brackets the boundary consistently.

## Options

1. **Intake at 65,536, fp16 KV.** No truncation at all.
2. **Intake at 65,536 with Q8 KV cache.** Roughly half the memory.
3. **Intake at 32,768, with a truncation rule for what overflows.**

## Decision

**Option 3.** Intake 32,768, analyst 32,768, structuralist 16,384, KV cache fp16.

### Why not the clean option

Footprints were computed from the model files themselves, not estimated. Llama 3.2
and Qwen3 have **no sliding-window attention** — every layer's KV cache scales with
context — while Gemma 4 keeps 40 of 48 layers on a 1,024-token window and gives its
8 global layers a *single* KV head each:

| model | KB/token | KV @32k | KV @64k |
| --- | --- | --- | --- |
| llama-3.2-3b | **112.0** | 3.76 GB | **7.52 GB** |
| qwen3-4b | 144.0 | 4.83 GB | 9.66 GB |
| gemma-4-12b | ~14 | 0.87 GB | 1.41 GB |

Intake is the agent that reads exhibits, so the cost lands exactly where it hurts.
**Option 1 peaks at 9.54 GB resident** (2.02 GB weights + 7.52 GB cache) against a
default GPU wired limit near 10.6 GB on a 16 GB machine, before llama.cpp's compute
buffers, with the OS and an editor competing for the same memory. It might hold.
Across twelve nights and 356 items, "might" is the wrong property.

**Option 2 was rejected because its cost is unknown rather than acceptable.** There
is no measurement of Q8 KV quality for this model on this task, and guessing one
would be the failure this project spends its effort avoiding. It also has a
structural problem: KV quantisation appears in neither the cache key nor the model
fingerprint, so outputs would change while keys stayed identical — the mutable-tag
trap in a new place.

**Option 3 peaks at 7.85 GB**, and that peak is the *analyst*, not intake. Models
load one at a time, so that is the whole footprint.

**Correction, 2026-08-17.** The 0.87 GB figure for Gemma at 32,768 was derived from
the architecture and is wrong about the runtime, which allocates full-length KV for
every layer regardless of the sliding-window bound the model supports — about
336 KB/token, so 11.0 GB at 32,768. The server refused to load it. Final windows,
each **verified by bracketing** rather than computed:

| agent | window | requirement (server-reported) | margin |
| --- | --- | --- | --- |
| intake | **32,768** | documents; budget 29,968 | — |
| analyst | **16,384** | 1,598 prompt + 12,000 budget = 13,598 | 17% |
| structuralist | **8,192** | 1,064 prompt + 386 completion = 1,450 | 5.6× |

**The reasoning budget was not lowered.** Observed reasoning runs to 5,329 tokens
with wide variance, and a budget sized to that would produce exhaustion failures
rather than occasionally risking them. 16,384 holds the full 12,000.

**Truncation is unaffected.** The document budget derives from *intake's* window,
which is unchanged and verified at 32,768, so the rule still bites on the same
twelve exhibits with the same parameters.

### The truncation rule, with its parameters fixed here

At 32,768, **twelve** exhibits overflow. They belong to **three tickers**: BXP (6
items, 57–59k tokens each), FCX (4 items, 33–36k), PRU (2). Three of 120 tickers.

The count is twelve rather than the eleven quoted while this was being decided,
because the gate estimates at 3.5 characters per token while that survey used 3.7.
The conservative estimator catches one more PRU filing, which is the direction a
refusal gate should err in.

> **Head-and-tail retention.** Keep the first **24,000 tokens** and the last
> **4,000 tokens** of the exhibit, drop the middle, and insert an explicit elision
> marker naming how much was removed. Applied identically to every exhibit,
> regardless of size or ticker.

**The counts are fixed now, in this document, deliberately.** Left open they would
become a parameter someone tunes after seeing a result, and a truncation length
chosen with a score in view is a researcher degree of freedom rather than a
preprocessing step. They are frozen with the corpus alongside the context lengths.

**Why 24,000 and 4,000.** The budget is 32,768 less an 800-token template reserve
and a 2,000-token output reserve, leaving 29,968. A 28,000-token target uses it with
**1,968 tokens of margin — 7.0% of the target**, not the 10% an earlier draft of
this document claimed. The arithmetic:

| true chars/token | 28,000 tokens estimated at 3.5 → 98,000 chars | actual tokens | fits 29,968? |
| --- | --- | --- | --- |
| 4.0 | 98,000 | 24,500 | yes |
| 3.7 | 98,000 | 26,486 | yes |
| 3.5 | 98,000 | 28,000 | yes |
| **3.3** | 98,000 | **29,697** | yes, by 271 |
| 3.0 | 98,000 | 32,667 | **no** |

The margin covers ratio error down to about 3.3 characters per token, which is
already below anything observed (3.7 and 4.0 from real rejections). So the margin
holds — but it holds by less than the earlier draft asserted, and a claim the
numbers do not support has no business in an ADR.

**The margin is nevertheless not what guarantees correctness.** Trusting it would
mean a bad ratio produces a *run-time* failure, which is the class of failure this
whole document exists to eliminate. So the rule **enforces the invariant instead**:
after cutting, the result is re-estimated, and if it is still over budget the head
and tail are shrunk together and it is re-checked, until it genuinely fits. Ratio
error can then cost a slightly shorter document. It cannot cost a night.

Head and tail shrink *together*, preserving the 6:1 shape. Shrinking the head alone
would never converge at a small budget, where the fixed tail can exceed the whole
allowance by itself.

The 6:1 split follows the shape of an earnings release. The head carries what the
document is *for*: headline results, the metrics table, management commentary, and
usually guidance. The tail exists for one narrow reason — a guidance or outlook
table often sits *after* the financial statements — and catching that needs a few
thousand tokens, not eight. The elided middle is reconciliation schedules,
GAAP-to-non-GAAP bridges and, for BXP as a REIT, property-level tables. Dropping
the middle is the choice that loses least; **head-only would systematically drop
guidance for exactly the largest filers, and guidance is what moves a five-day
window.**

### Why the truncation objection does not survive at this scale

When it looked as though truncation would bite on 54% of the corpus, the objection
was decisive: it would rewrite the majority of the sample and correlate with filer
size. At three named tickers that objection fails on its own terms:

- Every affected item is **identifiable in advance** and flagged per item.
- BXP and FCX are truncated **in both bands equally**, so the leakage difference —
  the number the ambiguous band exists to produce — is protected by the same-ticker
  constraint that has already paid for itself twice. PRU is truncated once in each
  band, so the same holds for it.
- The affected set is small, named, and reportable.

### Pre-registered sensitivity check

**The primary result will be reported both with and without BXP, FCX and PRU,
regardless of what the comparison shows.** Declared here, before any score exists,
because a robustness check run afterwards and mentioned only when favourable is a
different claim from one committed to in advance. If the two differ materially,
that difference is a finding and is reported as one.

### What the record holds, and what it means

**The frozen exhibit hash stays the hash of the full document EDGAR served.**
Truncation is recorded beside it as a processing step — rule name, parameters, and
a per-item flag with the number of characters elided — never folded into it.

This follows ADR 0005 rather than departing from it: `Document.id` hashes the bytes
exactly as they arrived, so it is "an honest record of the source rather than of our
rendering", and quarantine was already a rendering step that does not disturb it.
Truncation is another. Hashing the truncated text would make the hash mean "what we
chose to show the model", and the record would lose its only claim to reproducibility
against EDGAR.

The truncated text stays `UntrustedText` through the transformation. Returning a bare
string would push re-labelling onto every caller, and a caller that forgot would
silently launder filed text into trusted text.

## Addendum, 2026-08-31 — the margin was falsified, and the reasoning behind it was the defect

**PRU 2026-04-14 overflowed intake's window after truncation.** Cut to 98,121 characters,
estimated at ~28,035 tokens against a 29,968-token budget, and refused by the server.

The table above says the margin "covers ratio error down to about 3.3 characters per
token, which is already below anything observed (3.7 and 4.0 from real rejections)".
That claim rested on **two** data points. It is now falsified with 135:

| | min | p05 | median | max |
| --- | --- | --- | --- | --- |
| intake prompt, chars/token, measured on 135 completed items | **3.017** | 3.285 | 3.887 | 5.095 |

- **19 of 135 items (14%) tokenise below the assumed 3.5.**
- **8 of 135 (6%) fall below 3.3** — the value called "below anything observed".
- A 98,121-character cut fits only if the true ratio is **≥ 3.274**, so roughly one
  truncated exhibit in twenty was always going to overflow. PRU is not bad luck; it is
  the 6% arriving.

**The estimator is not conservative.** `estimate_tokens` divides by the ratio, so a
*higher* ratio predicts *fewer* tokens. At 3.5 the gate under-estimates for 14% of
documents. It sits near the middle of the distribution when a refusal gate needs to sit
at or below its floor. The ADR reasoned about the direction of the error correctly and
then chose a value from the wrong end of a two-point sample.

### What it costs to move

| ratio | exhibits truncated | cut to | completed items needing a re-run |
| --- | --- | --- | --- |
| 3.5 (current) | 12 | 98,121 | — |
| 3.3 | 14 | 92,521 | 2 |
| 3.2 | 16 | 89,721 | 2 |
| **3.0** | **18** | **84,121** | **2** — BXP 2026-01-28, FCX 2026-01-22 |

### The reframe, which is the argument for the pair rather than either half

**With verification in place the ratio stops being a safety property and becomes an
efficiency one.**

| the ratio is | consequence |
| --- | --- |
| too high | a **visible pre-flight refusal**, naming the document and the ratio that would have fitted |
| too low | slightly more truncation than strictly necessary |

Neither fails silently, and that is the whole point. It is why **3.0 does not have to
be provably below all ~570 remaining documents.** Asserting that it was would be a
*fourth* instance of "a margin chosen from the observed range" — the error made in this
ADR with n=2, in the analyst reasoning budget, and in the `budget_exhausted`
classification. Three times is a pattern; committing to it a fourth time while writing
the correction would be remarkable.

So 3.0 is chosen as **a good working value backed by 135 measurements**, not as a
guarantee. The guarantee is the verification, and the ratio only has to be close
enough that the verification rarely fires.

### The remedy is both halves, and the second is the one that matters

**Lower the ratio to 3.0**, grounded in 135 measurements rather than two, and re-run the
two affected completed items.

**The truncation sensitivity partition grows from 12 exhibits to 18, and that is recorded
here, dated 2026-08-31, with its cause.** It is a change to a pre-registered partition, so
the reason it is legitimate has to be stated rather than assumed: the growth is driven by
a **measurement of tokenisation**, not by anything about a result. **No score exists
anywhere** — not one forecast has been scored — so there is no outcome the partition could
have been grown toward. Written down now so that it cannot later look as though it
followed from seeing something.

A third check the pre-flight now performs falls out of this: a completed item whose
exhibit the *current* rule would cut differently is reported as **stale**. Changing the
ratio changes what the model was shown, and an item scored on a document the rule would
no longer produce is a silent inconsistency that nothing else would surface.

**And verify the cut against the real tokeniser in the pre-flight**, because lowering the
ratio alone is *structurally the same reasoning that just failed* — a margin chosen from
the range observed so far. Better informed at 135 points than at 2, and still an
extrapolation: a 136th document below 3.0 fails identically and just as silently.

**No new dependency is needed.** The server reports `prompt_tokens` on every response, so
a completion capped at one token returns the exact count — the same mechanism the context
probe already uses (§4). Twelve to eighteen prefill calls in `map corpus run --check`,
a few minutes, once.

**Verify and refuse, never verify and shrink**, and the reason descends directly from
this ADR's rejection of Q8 KV quantisation.

Q8 was rejected partly because it is *"a server-side setting invisible to the cache key
and the model fingerprint"* — outputs would change while keys stayed identical. Cutting
a document until the server's tokeniser says it fits has exactly that shape, one level
worse: **the artifact itself would depend on a server-side setting.** The same corpus on
a different build, or after a model reload, would produce different documents under the
same frozen record, and `Document.id` would no longer mean what ADR 0005 says it means.

So the cut stays a pure function of the configured ratio — deterministic, reproducible
from the record alone, recorded — and the pre-flight *measures* whether that function's
output actually fits. **A document whose content depends on a server-side tokeniser is
not reproducible**, and no amount of verification would make it so.

### The refusal names its own remedy

The pre-flight reports the ratio each over-budget document *would* have fitted at,
floored rather than rounded — 3.105 rounded up to 3.11 would name a value that still
does not fit, and a suggestion has to be right in one direction only. The named value is
the densest document's, not the first's, so acting on it does not refuse again on the
next run.

A refusal that carries its own next step is one decision. A refusal that does not is an
investigation.

That is this ADR's own §4 principle applied one level down: **the configuration states a
number and the pre-flight measures the server, rather than trusting the number.**

## Addendum, 2026-09-01 — the re-run set, and a pre-commitment about PRU

The corrected basis was applied and the band finished. Reconciling what it touched
found **six** stale items, not the two identified earlier, and the reason the earlier
count was short is recorded in [[../Findings & Incidents#39]]: three of them ran
**untruncated** at 3.5, so they carried the untruncated freeze digest and sat in the
majority group. A content digest records the input that *was* used; it cannot represent
the input that *would* have been used under a different parameter.

**The re-run set is nine**, and every item qualifies on **document size** — the
property the ratio change acts on — not on its outcome:

| | items |
| --- | --- |
| stale: the rule now cuts them differently | FCX 2026-04-23, BXP 2026-04-28, CP 2026-04-29, FCX 2026-07-23, BXP 2026-07-28, CP 2026-07-29 |
| already correct, re-run only because `rule_id` moves their freeze digest | BXP 2026-01-28, FCX 2026-01-22 |
| failed under the old basis | PRU 2026-04-14 |

**The two relabelled items cost nothing and change nothing.** Their prompts are
byte-identical, and every call — seven across the two, including BXP's degeneration
retry at `attempt=1` — was confirmed present in the response cache by reconstructing
its key from the recorded trace. They will replay, not resample. Had they missed the
cache, two valid forecasts would have been replaced by two different ones at
temperature 0.7, and that would have needed deciding rather than assuming.

### The pre-commitment on PRU, written before it runs

PRU 2026-04-14 is 105,272 characters. It sits inside the band the ratio change moves
and qualifies exactly as CP and FCX do. It also happens to be the item whose failure
exposed the defect, which is why the commitment is written down first:

> **If PRU succeeds under the corrected basis it is scored**, and the clean band's
> failures fall from six to five. **If it fails again it stays a failure and gets no
> further retry** — no third attempt, no parameter moved to accommodate it.

Included on document size, judged on neither outcome. Recorded now because "the item
that motivated the fix also happens to pass under it" is a sentence that needs its
decision rule fixed in advance.

### The ambiguous band cannot repeat this

Nine of its exhibits are truncated under the corrected basis — BXP ×3, CP ×2, FCX ×2,
CCI, PRU — and all nine are already in the frozen record's `applies_to`. The band has
not started, so every one is cut at
`head_tail_v1(head=24000,tail=4000,ratio=3.0)` from its first attempt. There is no
old-basis item to become stale.

## Addendum, 2026-09-01 — the truncated set is five companies, and cannot be a sensitivity analysis

Eighteen truncated items sounds like a subset of a 120-company corpus. It is not:

| company | items | elision |
| --- | --- | --- |
| **BXP** | 6 | 60.3 – 61.7% |
| **FCX** | 5 | 12.9 – 36.3% |
| **CP** | 4 | 6.7 – 19.0% |
| **PRU** | 2 | 20.2 – 27.1% |
| **CCI** | 1 | 7.1% |

**Five companies of 120, and BXP alone is a third of the set** — every one of its six
filings elided at ~60%, because a REIT's earnings release carries property-level tables
that nothing else in the corpus has.

### Why the pre-registered sensitivity check must be withdrawn as stated

This ADR pre-registered *"the primary result reported both with and without BXP, FCX and
PRU"*. That framing is sound — it names companies. **A truncated-versus-untruncated
split is not**, and would have been the natural way to run it:

> Truncation status is **perfectly confounded with company identity.** Removing the
> truncated items removes five specific companies, so any difference is a difference
> between *those five companies* and the other 115 — a REIT, a copper miner, a railway,
> an insurer and a tower operator — and not between truncated and untruncated inputs.
> There is no within-company contrast anywhere in the design: no company appears on both
> sides.

The check therefore stays exactly as ADR 0020 wrote it — a **leave-these-companies-out**
robustness report — and is never described as measuring an effect of truncation.

### What is reported instead: the gradient, described and not tested

Elision fraction is continuous and spans an order of magnitude. Clean band, nine items:

| | | |
| --- | --- | --- |
| lowest | CP 2026-04-29 | **6.7%** |
| highest | BXP 2026-01-28 | **61.7%** |

Reported per item alongside the result, so a reader can see whether the heavily-elided
items sit anywhere unusual.

**This describes the gradient. It does not test it.** Eighteen items across both bands,
clustered into five companies with BXP contributing a third at one end of the range, is
not a sample anything can be regressed on — the effective n is closer to five than to
eighteen, and the design has no within-company variation to separate elision from
company. Any slope fitted here would be a company effect wearing a continuous variable's
clothes. Stating that now is cheaper than being asked it later.

## Consequences

- `context_tokens` joins the configuration per agent and is frozen with the corpus,
  like the price vintage: it is a property of the run, not of the machine.
- A startup validator rejects `max_tokens + 512 > context_tokens`. That pair was
  set independently into contradiction, and the contradiction is what TSLA was.
- **`map corpus run --check` now probes the server for its real context** rather
  than trusting the configured number (§4 below), and refuses if any exhibit cannot
  fit, naming the binding agent.
- Context overflow is reclassified as a **terminal** failure. The halted run
  recorded eight of them as transient `other`, which on resume would have retried
  them and consumed the failure allowance afresh every pass, halting the run
  repeatedly on items that could never succeed.
- Budget exhaustion stays **transient**, because the analyst samples at temperature
  0.7 and a second attempt genuinely explores a different reasoning path. The same
  reason would be terminal for a temperature-0 agent; the distinction is about the
  sampling, not the exception.

## §4 — Why the pre-flight probes rather than checks

Rejecting Q8 KV quantisation rested partly on it being a server-side setting
invisible to the cache key and the fingerprint. **Context length is the same kind of
setting**, and the same reasoning applies one step further: a pre-flight that
compared `config` to a computed document size would have passed the halted run
happily, because both numbers were internally consistent and neither was the server.

So the probe asks — and it asks by **bracketing**, not by reading the server's
error prose.

The first version sent one oversized request and parsed the reported window out of
the rejection. That worked for one agent and failed for two: they rejected the probe
without naming a context at all, so their windows could not be verified. It was also
vendor coupling in application code — a dependency on how one particular server
phrases an error, which `CLAUDE.md` §3 forbids for exactly this reason.

The bracket needs no number. Two requests per agent:

- one sized **just under** the configured window, which must be **accepted**
- one **comfortably over**, which must be **rejected**

Together those pin the window relative to the configuration on any backend,
including one that says nothing at all or simply drops the connection. The filler is
a repeated common word, so the prompt's token count tracks the repeat count on any
byte-pair vocabulary — which is what lets the probe target a size directly instead
of through a characters-per-token ratio it would otherwise have to assume.

A parsed number is retained **only as a presentation refinement**: shown beside the
bracket when it happens to be there, never branched on. A test asserts a verbose
server and a terse one reach the same verdict.

If the under-probe is rejected, the server's window is smaller than configured and
the run refuses to start. A server with *more* context than configured is not a
failure — the run stays inside its configured budget, so the guarantee holds — and
the report says so rather than silently passing.

This is the same move as the grammar probe, and for the same reason: **measure the
backend's behaviour rather than assume it.**
