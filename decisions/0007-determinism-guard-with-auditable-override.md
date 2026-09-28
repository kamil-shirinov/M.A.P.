# 0007 — Determinism guard with an auditable override

Status: Accepted · Date: 2026-08-09 · Phase 1

## Context

`CLAUDE.md` §6 lists `temperature=0` for Agents 1 and 3 among the
non-negotiables. Agent 2 is deliberately excluded — scenario reasoning is the one
place sampling diversity is wanted.

The rule is easy to violate and the violation is invisible. A structuralist run at
`temperature=0.4` still emits a schema-valid `ScenarioSet`, still passes every
validator, still writes a well-formed `forecast.json`. Nothing looks wrong. The
damage only appears later, when the run cannot be reproduced from its manifest and
the cache serves an answer that a re-run would not produce — by which point the
result may already have been scored.

So it needs enforcing rather than documenting. The question is what enforcement
does when someone genuinely wants to violate it.

## Options

1. **Document only.** The rule survives exactly as long as attention does.
2. **Hard block, no override.** Correct until the first time it is genuinely in the
   way. Then it invites the worst outcome available: someone deletes the validator
   under time pressure, and the run leaves *no* trace of the violation at all. A
   guard that can only be satisfied by removing it is a guard that will be removed.
3. **Warn but always allow.** Warnings scroll past. Nothing reaches the artifact.
4. **Block by default, with an explicit, auditable override.**

## Decision

The guard stays and rejects by default, raising `DeterminismPolicyError` — a
`ConfigurationError`, therefore fatal and never retried.

It is overridable by **`models.allow_nondeterministic`**, default `false`. When
set:

- the configuration loads instead of raising;
- a `determinism_override_active` warning is emitted at startup, naming every
  affected agent and its temperature;
- **the flag is recorded in the run manifest**, so any run produced under it is
  marked. This is the part that matters. A warning is ephemeral; the manifest is
  the thing Phase 2 reads when deciding whether a result is admissible.

The override must be set deliberately in config or environment. There is no CLI
flag for it, because a per-invocation escape hatch is one someone reaches for
without thinking.

**Phase 3's self-consistency ensembling targets Agent 2, not Agent 3.** Agent 2 is
already free to sample — it is not covered by the guard at all. So the override
should rarely, if ever, be needed, and a request to set it is worth questioning
before it is granted.

## Consequences

- A misconfiguration fails at startup with a message naming both remedies, rather
  than producing an unreproducible forecast that looks ordinary.
- Runs split into two populations — guarded and overridden — and the manifest is
  what distinguishes them. **The Phase 2 evaluation harness must read that flag
  and either exclude overridden runs or report them separately.** Scoring the two
  together would silently mix reproducible and unreproducible results. This is a
  dependency on a module that does not exist yet, and it is recorded here so it is
  not discovered later.
- The guard covers only what configuration can see. It cannot stop a caller
  constructing `SamplingParams` directly with a non-zero temperature; that path is
  governed by review, not by this validator.
- `temperature != 0.0` is an exact float comparison. That is correct here — the
  value comes from a config file where a human wrote `0.0`, not from arithmetic —
  and it deliberately rejects `1e-9`, which is not determinism.
