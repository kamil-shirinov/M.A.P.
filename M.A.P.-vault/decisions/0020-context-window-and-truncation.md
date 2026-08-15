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

### The truncation rule, with its parameters fixed here

At 32,768, eleven exhibits overflow. They belong to **three tickers**: BXP (6
items, 57–59k tokens each), FCX (4 items, 33–36k), PRU (1). Three of 120 tickers.

> **Head-and-tail retention.** Keep the first **24,000 tokens** and the last
> **4,000 tokens** of the exhibit, drop the middle, and insert an explicit elision
> marker naming how much was removed. Applied identically to every exhibit,
> regardless of size or ticker.

**The counts are fixed now, in this document, deliberately.** Left open they would
become a parameter someone tunes after seeing a result, and a truncation length
chosen with a score in view is a researcher degree of freedom rather than a
preprocessing step. They are frozen with the corpus alongside the context lengths.

**Why 24,000 and 4,000.** The budget is 32,768 less an 800-token template reserve
and a 2,000-token output reserve, leaving 29,968; 28,000 uses it with ~1,900 tokens
of margin, which matters because the token estimate carries roughly ±10%
uncertainty and the estimate must never be the thing that overflows.

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
  constraint that has already paid for itself twice.
- The affected set is small, named, and reportable.

### Pre-registered sensitivity check

**The primary result will be reported both with and without BXP, FCX and PRU,
regardless of what the comparison shows.** Declared here, before any score exists,
because a robustness check run afterwards and mentioned only when favourable is a
different claim from one committed to in advance. If the two differ materially,
that difference is a finding and is reported as one.

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

So the probe asks. One deliberately oversized request per agent, rejected before
any generation, and the rejection names the real window:

    the request (13830 tokens) exceeds the available context size (8192 tokens)

If the server reports less than the configuration promised, the run refuses to
start and says which is which. A server with *more* context than configured is not
a failure — the run stays inside its configured budget, so the guarantee holds.

This is the same move as the grammar probe, and for the same reason: **measure the
backend's behaviour rather than assume it.**
