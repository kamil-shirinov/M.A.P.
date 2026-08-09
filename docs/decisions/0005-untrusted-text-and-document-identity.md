# 0005 — Untrusted text as a type, and document identity over raw bytes

Status: Accepted · Date: 2026-08-09 · Phase 1

## Context

News text — from a local directory or an RSS feed — is untrusted input that flows
into a model whose output is parsed as numbers. `CLAUDE.md` §9 requires that feed
text be delimited and quarantined, and never read as instructions.

Two questions follow, and they pull in opposite directions.

**When does quarantine happen?** If a document is wrapped in delimiters at load
time, then `Document.text` is no longer what arrived — it is a rendering. Hashing
it produces an id for a string that exists nowhere outside this program, and the
audit trail stops being an audit trail.

**How is quarantine enforced?** A convention that says "remember to delimit feed
text" is enforced by whoever is paying attention that day. The failure it guards
against — untrusted text reaching a slot the model reads as instructions — is
invisible in review, because a correct call and an incorrect one differ only in
which argument a string was passed as.

## Options

1. **Quarantine at load, hash the quarantined text.** Simple, and destroys the
   provenance guarantee: `source_doc_ids` would identify our rendering rather
   than the source.
2. **Quarantine at load, hash the raw bytes.** Honest id, but `Document.text` is
   then permanently pre-wrapped and cannot be re-rendered for a different prompt
   template or a different delimiter scheme.
3. **Keep text raw, quarantine at render, enforce by convention.** Correct data,
   unenforced rule.
4. **Keep text raw, quarantine at render, enforce in the type system.**

## Decision

**`Document.text` stays raw.** The id is `sha256` over the bytes exactly as
fetched, before any decoding or normalisation, prefixed `sha256:`. It is an
honest record of what actually arrived, and it is stable regardless of how the
text is later rendered.

**Quarantine happens at render time**, in the prompt renderer, which is the only
component that knows a template's slot structure.

**`core` defines two distinct `NewType`s over `str`:** `TrustedText` and
`UntrustedText`. The renderer takes them in **separate maps** and applies
delimiters and escaping only to the untrusted one. Because two `NewType`s over
the same base are mutually unassignable — and a plain `str` satisfies neither
without an explicit constructor call — mypy rejects untrusted text reaching a
trusted slot, and rejects unlaundered `str` reaching either. The guarantee is
type-checked, not conventional.

**Taint propagates through the pipeline.** `MaterialFacts` (Agent 1's output) and
`ScenarioNarrative` (Agent 2's output) carry `UntrustedText`, not `TrustedText`.
Both are model output derived from feed text, and both are interpolated into the
*next* agent's prompt. An injection surviving Agent 1's compression is still an
injection. Marking only `Document` would launder the taint at the first agent
boundary, which is precisely where it matters most.

## Consequences

- `mypy --strict` and the `pydantic.mypy` plugin are load-bearing, not hygiene.
  The plugin is what gives `BaseModel.__init__` a typed signature; without it,
  pydantic models accept `Any` and the whole guarantee evaporates silently. It is
  enabled in `pyproject.toml` and must stay enabled.
- The enforcement is **static only**. At runtime a `NewType` is the identity
  function, and pydantic validates `UntrustedText` as `str`. Nothing raises if
  untyped code passes a bare string. This protects the codebase under CI; it is
  not a runtime sandbox, and it must not be described as one.
- Laundering is explicit and greppable: every `UntrustedText(...)` call site is a
  place where raw text formally enters the system. There should be very few, and
  they should all be in `mapf.data`.
- Re-rendering the same document under a new template or delimiter scheme changes
  no ids. Prompt evolution does not invalidate document provenance.
- Hashing raw bytes means two documents differing only in line endings or encoding
  are distinct. That is correct — they are different bytes — but it means the
  cache will miss on a re-fetch that normalises whitespace, and the trace will
  show it.
