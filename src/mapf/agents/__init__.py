"""The three agents, and an honest statement of what they cannot catch.

An agent here is a contract, not a model: `(input type) -> (output type)`, with
the model behind it chosen by configuration (`CLAUDE.md` §4). Each receives its
dependencies as Protocols and constructs none of them, so `import-linter` can
guarantee this package never reaches `providers`, `data` or `settings` — which is
what makes the whole suite runnable with the inference server switched off.

## What this layer guarantees

- **The grammar guarantees shape.** Under constrained decoding the sampler cannot
  emit a missing field, a wrong type, a string outside its length bounds, or a
  number outside its range. Those failures are unreachable, not merely rejected.
- **The validators guarantee cross-field consistency.** Weights summing to one and
  `bearish < base_case < bullish` span fields, so no grammar can express them;
  they are enforced in `ScenarioSet`, and the repair loop exists to answer them.

## What this layer does not guarantee, and no layer downstream does either

**Neither of the above says anything about whether the numbers mean anything.**

A forecast can be schema-valid, internally consistent, fully traced, and built
entirely on a premise the model invented. If Agent 1 hallucinates a fact, Agent 2
reasons impeccably from it and Agent 3 structures the result perfectly, every
check in this project passes and the output is worthless. Nothing here detects
that, because nothing here compares the forecast to reality — **that is Phase 2's
job, and it is the only thing that can do it.**

Three specific gaps, stated so they are not discovered later:

1. **Hallucinated premises.** The templates instruct the model to reason only from
   the provided facts. That is an instruction, not a constraint. A model that
   invents a fact produces output indistinguishable from one that did not.
2. **Training-cutoff leakage.** The templates forbid using knowledge of what
   happened afterwards. Also an instruction. On a well-known ticker the model very
   likely knows, and no check here can tell recall from reasoning (`CLAUDE.md` §9).
3. **Prose quality.** Agent 2's output cannot be schema-checked. It is verified for
   non-emptiness and plausible length and nothing else — deliberately, because
   elaborate validation of prose would produce confidence without evidence. The
   trace is the real record, and a human reading it is the real check.

The forecasts this layer produces are **falsifiable, not verified.** That
distinction is the point of the project, and confusing the two would undo it.
"""
