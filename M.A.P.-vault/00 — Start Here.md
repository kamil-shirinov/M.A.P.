# M.A.P. — Start Here

> Open Obsidian and point a vault at `~/Desktop/M.A.P./M.A.P.-vault/`.
> The ADRs, STATE.md and these learning notes then all live in one graph.

---

## What this project is

M.A.P. reads financial news with three local AI models and produces a probabilistic price
forecast — three weighted scenarios, rendered as a chart.

**But the forecast is the demo, not the point.** The point is everything around it: a full audit
trail of every model call, reproducibility by identifier, structural defences against untrusted
input, and an evaluation harness that measures whether the forecasts are any good — including
being willing to report that they aren't.

The one-line version to have ready: *"I built an LLM forecasting pipeline, measured it properly
against baselines, and can tell you exactly how wrong it is."* Most people who build these can't
finish that sentence.

---

## How the vault is organised

| Note | What it's for |
|---|---|
| **00 — Start Here** | This note. Orientation. |
| [[Concepts]] | Every technical term used in the project, in plain English, anchored to where it appears here. |
| [[Development Timeline]] | What happened, in order, and why. The narrative the ADRs assume you already know. |
| [[Findings & Incidents]] | Real bugs and discoveries. |
| [[Guard Audit]] | Every check in `src/`, what its name implies against what it verifies, and where those differ. |
| `decisions/` | The ADRs. Formal records: Context / Options / Decision / Consequences. |
| [[STATE]] | Where the project is right now. Updated every session. |

**Reading order if you're catching up:** Start Here → [[Development Timeline]] → [[Findings & Incidents]]
→ then ADRs as they come up, with [[Concepts]] open beside you.

---

## The four phases

**Phase 1 — The Machine.** *Complete.* Nine modules, 727+ tests, a working end-to-end pipeline.
Produced no knowledge, by design.

**Phase 2 — The Evidence.** *In progress.* A pre-registered corpus of 727 forecasts over 120
companies, baselines to beat, and proper scoring. This is where the project becomes a quantitative
result rather than a demo.

**Phase 3 — The Calibration.** Fit a correction to the measured miscalibration, then measure the
correction. Contains the only genuinely trained models in the project.

**Phase 4 — The Surface.** A UI, packaging, publication.

Each phase gates the next. Phase 3 fits a curve to Phase 2's output — there is nothing to fit
before then.

---

## What to understand versus what to skip

You do not need to be able to implement CRPS or derive a block bootstrap. Nobody will ask.

**Be able to explain the decisions:**

- Why three agents — and that it's still an untested hypothesis
- Why local inference, and what it costs
- Why the response cache is infrastructure rather than an optimisation
- Why the corpus is built the way it is: leakage, overlapping windows, point-in-time alignment
- Why calibration became the primary question and directional skill did not
- What the 66.3% incident says about what this system can and cannot guarantee

Those are conceptual. You made every one of those calls yourself.

---

## Keeping this current

When a term appears that you don't recognise, add it to **Concepts** immediately — even just the
word. Future you can fill it in; future you cannot remember what confused you.

At the end of each development session, ask Claude Code:

> Append to `M.A.P.-vault/Development Timeline.md`: what changed today and why, in five lines. Add
> any new incident to `M.A.P.-vault/Findings & Incidents.md`. Add any term a reader might not
> know to `M.A.P.-vault/Concepts.md`.
