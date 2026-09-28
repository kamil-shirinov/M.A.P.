# 0006 — `justification` is emitted before the figures

Status: Accepted · Date: 2026-08-09 · Phase 1

## Context

Agent 3 produces a `ScenarioSet` under constrained decoding. Pydantic preserves
field declaration order when generating the JSON Schema, and a constrained
decoder emits object keys in schema order — so **field order in `Scenario` is not
cosmetic, it fixes the order in which the model commits to tokens.**

A `Scenario` holds one string and three numbers: `justification`,
`probability_weight`, `price_modifier_pct`, `annualised_vol`. Whichever comes
first is generated without the others in context.

## Options

1. **Figures first, justification last.** The natural reading of the field name:
   the model states its numbers, then explains them.
2. **Justification first, figures last.**
3. **No opinion — let declaration order fall out of whatever reads well.** This is
   the option that actually loses, because the ordering takes effect whether or
   not it was chosen deliberately.

## Decision

**`justification` is declared first**, and the ordering is treated as part of the
contract rather than a formatting preference.

With figures first, the justification is generated conditioned on numbers that
are already fixed. Whatever the model then writes cannot change them; it can only
narrate them. That is rationalisation, and it makes the field near-useless as
evidence about how the forecast was reached.

With the justification first, the numbers are generated conditioned on the
reasoning. The text is in the context window when the sampler picks the digits of
`price_modifier_pct`, so it can shape them.

## Consequences

- **The justification cannot reference the final figures, because they do not yet
  exist in the token stream.** It will say things like "supply constraints and a
  soft guidance revision point to modest downside" rather than "-8.2% reflects
  ...". **This is the intended property, not a limitation.** A justification that
  quotes its own numbers is describing a decision already made; one that does not
  is part of making it.
- Any future reader of `forecast.json` should read `justification` as *reasoning
  that preceded* the figures, not as a caption for them. This is worth stating
  wherever the artifact is documented for humans.
- Field order in `Scenario` must not be changed for tidiness. A test asserts
  `justification` is first in the emitted decode schema, so the property is
  enforced rather than remembered.
- Phase 3's ablation study has an obvious variant to measure here: same model,
  same prompt, figures-first vs justification-first. This ADR is a hypothesis
  about conditioning, and it is testable. It should be tested rather than assumed
  once there is a scoring harness to test it with.
- The effect is real but bounded — a 4B model under a tight grammar has limited
  room to reason in 400 characters. Do not overclaim it.
