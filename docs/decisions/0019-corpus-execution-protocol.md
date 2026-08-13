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
