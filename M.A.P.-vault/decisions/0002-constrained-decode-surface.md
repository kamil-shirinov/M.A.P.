# 0002 — Narrow the constrained-decode surface

Status: Accepted · Date: 2026-08-09 · Phase 1

## Context

The Phase 1 forecast artifact is a single flat JSON object containing the three
scenarios alongside `run_id`, `as_of`, `ticker`, `spot_price`, `horizon_days`,
`source_doc_ids`, `model_versions` and `schema_version`. Read naively, that shape
implies Agent 3 emits all of it under constrained decoding.

Every field in that second group is already known to the pipeline before Agent 3
is called. `spot_price` in particular is the field that makes the forecast
scoreable at all: Phase 2 cannot compute CRPS or a log score without the price
the modifiers are relative to. Asking a 4B model to restate a number the pipeline
is holding invites a hallucinated value into precisely the field whose corruption
is least detectable — a wrong `spot_price` produces a well-formed, schema-valid,
silently meaningless forecast.

## Options

1. **Decode the whole object.** Matches the spec literally. Puts eight
   pipeline-owned fields, including `spot_price`, inside the model's output
   distribution.
2. **Decode the whole object, then overwrite the known fields.** The grammar
   still spends tokens on them, the trace still records fabricated values, and
   the overwrite silently masks a model that is behaving badly.
3. **Decode only the model-authored part and assemble the rest.**

## Decision

**Agent 3's contract returns `ScenarioSet` — the `scenarios` object and nothing
else.** The JSON Schema handed to `response_format` is generated from
`ScenarioSet` via `model_json_schema()`. `pipeline` constructs the full
`Forecast` from that plus the metadata it already holds.

**The file written to `runs/<run_id>/forecast.json` is byte-identical to the
agreed schema.** Only the decode surface shrinks; the artifact does not change.

The two-layer validation split follows from this and is stated here because it is
the reason both layers exist:

- **The grammar** guarantees shape — required keys, types, `0 < annualised_vol
  <= 3.0`, `justification` length 20–400, `horizon_days ∈ [1, 252]`. These are
  expressible in JSON Schema, so invalid tokens are unreachable to the sampler.
- **The grammar cannot** express `Σ probability_weight = 1.0 ± 1e-6` or
  `bearish < base_case < bullish`. Cross-field invariants are enforced by
  `@model_validator(mode="after")` on the pydantic model, and their failure is
  what the repair loop exists to answer.

## Consequences

- Two models where the brief has one, plus an assembly step. Cheap.
- A smaller grammar means fewer decode failure modes and fewer wasted tokens on a
  4B — which is the model Agent 3 was deliberately sized down to.
- One class of silent corruption becomes structurally impossible rather than
  merely unlikely: the model has no channel through which to express a
  `spot_price` at all.
- `schema_version` covers the on-disk artifact. If `ScenarioSet` and `Forecast`
  ever version independently, that needs revisiting; for Phase 1 they do not.
