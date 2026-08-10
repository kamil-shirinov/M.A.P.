# 0011 — Agent contracts, the repair loop, and what none of it guarantees

Status: Accepted · Date: 2026-08-10 · Phase 1

## Context

Three agents run in sequence. Each must hold when the model misbehaves, and the
three misbehave differently: Agent 1 can return nothing usable, Agent 2 returns
prose that cannot be checked, and Agent 3 returns structured output that can fail
invariants no grammar can express.

## Decision

**Agents receive Protocols and construct nothing.** `import-linter` forbids this
package from reaching `providers`, `data` or `settings` (ADR 0004), so a caching
provider is indistinguishable from a bare one and a fake is indistinguishable from
either. That is what makes the suite runnable with the server switched off.

**The repair loop lives in `structuralist.py`.** Not in the validator — a
validator that retries is no longer a validator. Not in the pipeline — how an
agent meets its contract is the agent's business.

**The repair prompt is a second template, `structuralist_repair.v1.md`**, not a
string assembled in Python. Appending the errors in code would put prompt text in
a `.py` file, which `CLAUDE.md` §4 forbids for precisely the reason that matters
here: a retry prompt is prompt content, and it must be versioned, hashed, and
recorded like any other.

**Validation errors are formatted from `loc` and `msg` only.** Pydantic's error
dicts also carry `input` — the rejected value — and that value is model output
derived from untrusted news. Feeding it back verbatim would re-inject what the
quarantine removed, through a slot we control and would have no reason to sanitise
(ADR 0005). The model's previous attempt *is* returned to it, but quarantined like
any other untrusted text.

**Exhaustion raises `ForecastRepairExhausted`, carrying the attempts, the errors
and the last raw response.** Never a coerced or partial object: a forecast patched
into validity by the pipeline is not the model's forecast, and scoring it in
Phase 2 would measure the patch.

**Agent 1 raises when no facts are extracted.** An empty answer is legitimate —
the template permits it rather than inviting fabrication — but a forecast built on
nothing is indistinguishable downstream from one built on something.

**Agent 2 is checked for non-emptiness and length, and nothing else.** Prose
cannot be schema-validated. Bounds catch refusals, truncation and generation
loops; anything more elaborate would manufacture confidence without evidence. The
trace is the real record. Stated as a decision rather than left as an omission.

## What none of this guarantees

The grammar guarantees shape. The validators guarantee cross-field consistency.
**Neither says anything about whether the numbers mean anything.**

A forecast can be schema-valid, internally consistent, fully traced, and built
entirely on a premise the model invented. If Agent 1 hallucinates a fact, Agent 2
reasons impeccably from it and Agent 3 structures the result perfectly, every
check in this project passes and the output is worthless.

The templates instruct the model to reason only from provided facts and not from
knowledge of what happened afterwards. **Those are instructions, not constraints.**
On a well-known ticker the model very likely knows how the story continued, and
nothing here can distinguish recall from reasoning (`CLAUDE.md` §9).

The forecasts this layer produces are **falsifiable, not verified**. Only Phase 2
compares them to reality, and confusing the two would undo the point of the
project. This is written in `agents/__init__.py` as well, where someone reading
the code will meet it.

## Consequences

- A repair sequence that exhausts its budget is **fully cached**, so the same
  failure reproduces from cold with zero calls to the provider. A reproducible
  failure is as much a requirement as a reproducible success, and there is a test
  asserting exactly that — it is also the test that would catch the
  attempt-index reasoning in ADR 0001 being wrong.
- Two templates for one agent means two hashes in the trace. Correct: the manifest
  should record which prompt produced which attempt.
- Agent 1's bullet parsing falls back to bare lines when the model returns no
  bullets. Pragmatic rather than principled — a 3B model formats inconsistently,
  and discarding a correct answer over its formatting would be worse. The raw
  response is in the trace either way.
