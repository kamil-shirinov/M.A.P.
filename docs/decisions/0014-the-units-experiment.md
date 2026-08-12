# 0014 — Diagnosing the first live run by experiment

Status: Accepted · Date: 2026-08-12 · Phase 1

## Context

The first live run produced a degenerate forecast: `0.05 / 0.0 / -0.1` where the
analyst had argued "moderate upward move / relatively flat / sharp downward move".

Two hypotheses were on the table, held by different people, and **both were wrong,
in opposite directions.** That is the part of this worth keeping.

- **Hypothesis A (units).** The two adjacent numeric fields were on different
  conventions — `annualised_vol` a fraction, `price_modifier_pct` percentage
  points — with nothing telling the model which. Read as fractions the output is
  coherent; read as percentage points it is nonsense.
- **Hypothesis B (conservatism).** The analyst was never asked for magnitudes at
  all, and the structuralist was told to "convert faithfully and **conservatively**
  rather than inventing precision it does not contain". Agent 2 was told not to
  produce numbers and Agent 3 not to invent them; someone has to, and Agent 3
  resolved the contradiction by being maximally conservative.

Hypothesis A's *evidence chain* was wrong: it assumed the analyst had stated large
moves that were mis-transcribed as small ones. The trace showed the analyst stated
**no numeric magnitudes whatsoever** — the only `%` tokens in its prose were
`46.3%` and `6.5%`, both fundamentals lifted from the source.

Hypothesis B was then advanced on the strength of that finding, along with the
claim that **"fixing units alone would probably not fix the output."**

## The experiment

A 2×2 over the two candidate instructions, Agent 3 only, against the *cached*
narrative from the failing run, at `temperature=0` with a fixed seed. Plus a second
block on the migrated schema.

The v1 schema had to be **reconstructed inline** rather than imported, because it
had already been migrated. Without that the control is not a control — the first
attempt at this experiment silently ran every cell against the new schema and was
worthless.

| variant | bull | base | bear | spread |
|---|---|---|---|---|
| 0 · control, shipped v1 prompt | 0.05 | 0.0 | -0.1 | 0.15 |
| i · units stated | **4.5** | 0.0 | **-8.2** | **12.7** |
| ii · conservatism clause removed | 0.05 | 0.0 | -0.1 | 0.15 |
| iii · both | **4.5** | 0.0 | **-8.2** | **12.7** |

## What makes the table trustworthy

**The control reproduced production exactly.** Cell 0 returned `0.05 / 0.0 / -0.1`
— the live run's output, digit for digit.

That single fact is what converts the other three cells from anecdote into
evidence, and it is the reusable methodological point:

- It proves the harness is faithful. The cached narrative, the schema, the sampling
  parameters and the prompt together reconstruct the failing conditions, so the
  variants differ from production in exactly one controlled way each.
- It proves the run was deterministic at `temperature=0` on this backend — which
  was an open question, not an assumption.
- Without it, a changed cell could mean "this instruction mattered" or "the model
  is noisy". With it, the second explanation is excluded.

**An experiment whose control does not reproduce the incident is not measuring the
incident.** That is worth more than this particular result.

## Findings

**Units is entirely binding. Conservatism is entirely inert.** Cells 0 and ii are
identical; cells i and iii are identical. Removing the conservatism clause changed
nothing at all; stating the units changed everything — an 85× wider spread.

So **hypothesis A was right about the mechanism** despite being wrong about the
evidence, and **hypothesis B was wrong**: fixing units alone would in fact have
fixed the output. The claim that it would not was reasoning that felt sound and was
not tested until now.

Second block, on the migrated fraction schema: the shipped v2 shape produced
`+0.045 / +0.005 / -0.065` — sensible fractions, correctly ordered. The old prompt
on the new schema produced `bull = base = 0.0`, which violates strict ordering and
would have gone to the repair loop. The validator does its job.

## Consequences

- The v2 migration is confirmed as the right fix, on evidence rather than argument.
- **The `justification` ceiling was lowered from 400 to 240 on unsupported
  reasoning.** The stated rationale — "a budget too small to paste into forces
  compression" — is contradicted here: at 240 the model still pasted and still
  truncated, at 240 instead of 400. A model copies because it was told to
  transcribe, not because it had room. Whether v2's "the justification is yours,
  not the analyst's" is what stops it is now measurable via transcription fidelity,
  and if it is, the ceiling should be raised again — 240 is tight for real
  synthesis and would be constraining the wrong thing.
- The fabricated `66.3%` reproduced in the control and in no other cell. **That is
  not evidence any of those instructions fixes hallucination** — one deterministic
  sample per cell cannot support that claim. It establishes only that this instance
  is summonable on demand, which is why it is pinned as a fixture: it lets the
  numeral check be tested against a real failure rather than a synthetic string
  written to be caught.
- Diagnostic, not prescriptive. Had cell ii improved the numbers, that would still
  not license letting a 4B derive magnitudes from prose — the same surface that
  fabricated 66.3%. An experiment says which lever moves; it does not choose the
  architecture.
