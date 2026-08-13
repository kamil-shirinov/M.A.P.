# 0017 — Hedge-rate probing measures metacognition, not capacity

**Status:** accepted · **Date:** 2026-08-13 · **Supersedes nothing**

## Context

Training-cutoff leakage is the trap named first in `CLAUDE.md` §9, and the corpus
split depends on knowing where each model's knowledge ends. None of the three
models publishes a usable cutoff: llama-3.2-3b self-reports one, gemma-4-12b-qat
publishes none, qwen3-4b-2507 has never disclosed one. So it had to be measured.

Two independent methods were run against a hand-built set of 173 dated corporate
events spanning 2023H1–2026H2, deliberately not designed around a single
"backbone" model, so that agreement between methods would be convergent validity
rather than a shared artefact:

- **hedge rate** — how often the model declines to answer a dated factual question
  ("I don't have information past …"). Expected to rise at the boundary.
- **recall accuracy** — whether it answers dated yes/no questions correctly.
  Expected to fall to chance past the boundary.

The working assumption was that hedging is a general capability, so the method
would apply to all three models and differ only in sensitivity.

## Options

1. **Assume the method transfers across models.** Read every model's boundary off
   its hedge curve, treat a flat curve as "no boundary in range".
2. **Treat a flat hedge curve as a broken probe** and fall back to recall alone.
3. **Establish applicability per model**, from the shape of the curve itself,
   before reading any boundary from it.

## Decision

**Option 3. Hedge-rate probing depends on a model having calibrated
metacognition — an accurate sense of the limits of its own knowledge — and that
is a training artefact, not a function of size. Applicability must be established
per model and is never to be assumed from parameter count.**

The measurement, all three models on the same 173-item set:

| model | params | hedge curve | verdict on the method |
| --- | --- | --- | --- |
| llama-3.2-3b-instruct | 3B | **100% at every period**, including well inside its own self-reported cutoff | over-hedges; no signal |
| gemma-4-12b-qat | 12B | 0% → 0% → 0% → 0% → 50% → 17% → 83% | the only usable curve |
| qwen3-4b-2507 | 4B | **0% at every period**, out to 2026H2 | under-hedges; confabulates instead |

The 3B refuses questions it can answer; the 4B answers questions it cannot. Both
failures are silent, and they point in opposite directions, so neither is
detectable without a second method to check against. Only the 12B produced a
gradient. Ordering by size predicts none of this.

### The qwen result, recorded separately

`qwen3-4b-2507` never hedges at any date and never beats chance at any date. It
has no working self-knowledge of its own limits: asked about events after any
plausible cutoff, it answers confidently and at random rather than declining.

**This is tolerable in a transcriber and would be alarming in a reasoner.** Its
role (Agent 3) is narrative → schema-valid JSON, where it is asked to restate
figures the analyst has already stated, not to supply facts. Supporting
measurement, not merely an argument: **transcription fidelity is 1.0 across every
run measured so far** — 6/6 scenarios parsed, 0 unparseable, 0 divergent,
`max_return_divergence = 0.0`. The figures leaving Agent 3 are the figures that
entered it, so its own knowledge is not reaching the numbers. Two runs is a small
sample and the metric stays in the manifest of every run precisely so this stops
being an argument and becomes a monitored quantity. **If fidelity ever drops below
1.0, this ADR's tolerance for the qwen result lapses with it.**

## Consequences

- **The intake boundary rests on answer rate, not hedge rate.** llama's answer
  rate falls 83% → 17% → 0% across 2023H2 → 2024H1 → 2024H2, agreeing with its
  self-report of December 2023. Two signals, one boundary.
- **The self-report is internally contradictory and is kept that way.** The same
  model in the same run said "December 2023" ×37 and "March 2023" ×10. Recorded
  unresolved: a model that disagrees with itself about its own boundary is
  evidence for how soft these boundaries are, and averaging it away would destroy
  exactly that evidence.
- **The analyst boundary rests on one signal.** Its hedge curve says ~2025H1; its
  recall curve was underpowered (~6 items per half-year, SE 0.20 against a 50%
  baseline) and could not confirm or contradict it. That is a design error in the
  probe, not a property of the model — corrected by a scoped re-run at 24 items
  per period over 2024H2–2026H1.
- **No structuralist boundary was measured at all.** Both methods are silent.
  Recorded as unknown, never as clean.
- **Generalisable beyond this project:** any leakage probe that relies on a model
  declining to answer is measuring the model's self-model, not its knowledge. The
  two coincide only when the model is calibrated about itself. Establish that
  first, on questions whose answers are known to be inside the training data,
  or the probe silently returns the model's disposition instead of its cutoff.
