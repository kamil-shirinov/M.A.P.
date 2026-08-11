# 0001 — Cache key composition

Status: Accepted · Date: 2026-08-09 · Amended 2026-08-10, 2026-08-11 · Phase 1

## Context

`CLAUDE.md` §6 mandates a disk cache on every LLM call, keyed
`sha256(model_id + prompt + sampling_params)`. On this hardware a 12B runs at
8–15 tok/s and a three-agent run costs three model swaps on 16 GB of unified
memory, so the cache is load-bearing infrastructure, not an optimisation.

The key as literally specified has two defects.

**(a) `model_id` is a mutable tag.** `CLAUDE.md` §9 already records this trap: a
registry can silently re-point `gemma4:12b` at different weights. If the tag is
the key, every subsequent lookup returns the *previous* model's answers, forever,
with nothing to surface it.

**(b) Wall-clock time in a prompt destroys the cache.** DoD criterion 5 requires a
second `map run` to complete in under 2 s with zero inference calls. Any `as_of`
timestamp rendered into a prompt changes the key on every invocation and
guarantees a total miss.

## Options

1. **Key on the tag, as specified.** Simplest; satisfies neither concern.
2. **Key on a weight fingerprint.** Correct, but the OpenAI-compatible surface is
   not guaranteed to expose one (see Consequences).
3. **Key on the tag, store the fingerprint, warn on mismatch.** Detects the
   problem but still serves the stale entry that triggered the warning.

## Decision

**Key on `model_fingerprint`, not on the tag.** The fingerprint is resolved once
at startup from `GET /v1/models`. The cache is *namespaced* by fingerprint, so a
change cold-misses rather than colliding.

Resolution is defensive and degrades in three steps, taking the strongest form
available:

1. **`digest`** — an explicit weight digest, if the response carries one
   (`digest`, `sha256`, or equivalent).
2. **`composite`** — a canonical hash over whatever identifying fields the
   response *happens* to carry beyond the id: `created`, `size`,
   `context_length`, quantisation, and so on. Every field is read with
   `.get()`, absence is tolerated, and the set of fields actually found is
   recorded. A composite is weaker than a digest — two builds of the same
   weights can collide, and an unrelated metadata change can spuriously
   invalidate — but it is strictly better than a bare tag, because a re-pointed
   tag almost always changes at least the size or the creation time.
3. **`tag`** — the id alone, when the response carries nothing else.

Reading extra fields from a standard endpoint is not vendor-specific code, and
does not breach `CLAUDE.md` §3, on two conditions that are part of this decision:
**no vendor is ever named**, and **no field is ever required**. The resolver asks
what is present and composes from that; it must not branch on which server it
believes it is talking to.

The manifest records `fingerprint_source: "digest" | "composite" | "tag"` and,
for a composite, **the exact list of fields used**. Without that list a composite
is unreproducible — a future version reading a different field set would compute a
different fingerprint for identical weights. When the source is `"tag"`,
`map health` reports that weight pinning is unavailable on this backend; the
limitation is stated, never hidden.

**No wall-clock value enters any prompt.** Where a date is genuinely needed, the
last trading date of the price window is passed instead. It is stable within a
day and is a more truthful statement of what the model can actually know.

**The decode schema is part of the key** *(amendment, 2026-08-10)*. For a call
made under constrained decoding the grammar is part of the request, not context
around it: change the schema and the set of reachable tokens changes, so the same
messages and the same sampling parameters can legitimately produce different
output. A key that omits it would serve, after a schema edit, output shaped by the
*previous* grammar — a false hit, which is the expensive direction. False misses
cost recomputation; false hits corrupt a result while leaving it looking entirely
normal.

It is folded into the prompt component rather than added as a fourth field, so the
key composition stays fingerprint + prompt + sampling + attempt, with "prompt"
meaning the whole request the model was asked to satisfy. `providers/keys.py` is
the single derivation, shared by the cache and the fixture replayer.

The complete key is therefore:

```
sha256(model_fingerprint, canonical(messages + decode schema), sampling, attempt)
```

**Repair attempts include the attempt index in the cache key.** The retry prompt
already differs from the first, because the validation errors are appended to it.
The index matters specifically for the *recurrence* case, which is the common
one: attempt 1 sends `P` and fails with errors `E`; attempt 2 sends `P+E` and
fails with the same `E`; attempt 3 would therefore render byte-identical to
attempt 2, hit the cache, and replay attempt 2's failed response without ever
calling the model. At `temperature=0` the loop would burn its remaining budget in
microseconds and raise. The index makes each attempt a distinct key.

### Observed, 2026-08-11 — the composite rung has nothing to build from

First contact with a real backend, recorded as fact so this is not re-litigated.

`GET /v1/models` returned exactly **three fields per model**:

| field | value | identifying? |
| --- | --- | --- |
| `id` | e.g. `qwen/qwen3-4b-2507` | yes — but it is the tag |
| `object` | `"model"` | no — constant across every entry |
| `owned_by` | `"organization_owner"` | no — constant across every entry |

No `digest`, no `created`, no `size`, no `context_length`, no quantisation. **Two of
the three fields are the same for every model on the server**, so a composite built
from them would carry exactly the information content of the tag while presenting
itself as something stronger. The resolver fell through to `tag`, which is correct:
the ladder degrades rather than manufacturing confidence.

The rung is not dead code — it fires on any backend that exposes more — but on this
one it cannot, and `fingerprint_source: "tag"` is the honest record.

### The richer data we knowingly declined

This backend **does** expose architecture, parameter count and quantisation — its own
UI displays them — but only through its **native** endpoint (`/api/v1/models`), not
the OpenAI-compatible `/v1/models` this project talks to.

Calling it would give a genuine composite fingerprint. We are not going to, because
`CLAUDE.md` §3 requires that switching backends be a config edit and forbids the
application from knowing which server it is talking to. A resolver that reaches for a
vendor-specific path has branched on vendor identity no matter how the call is
spelled, and the next backend would need a second branch.

This is the more useful record: **not "no data was available", but "richer data was
available behind a vendor endpoint and we declined it"** — a measured trade, made
once, with a known cost. The cost is that on this backend, cached results cannot be
pinned to exact weights, and `map health` says so on every run.

If that cost ever becomes unacceptable, the honest way to pay it is a
`ModelFingerprintSource` port with per-backend adapters in `mapf.data` — the same
shape as the price providers — not a conditional inside `openai_compat`.

## Consequences

- A genuine weight change invalidates the cache. That is the intended behaviour.
- Weight pinning degrades on backends whose `/v1/models` omits a digest.
  Application code must not reach for a vendor-specific endpoint to recover one —
  that would breach `CLAUDE.md` §3. The composite fallback, the manifest flag and
  the `map health` warning are the accepted mitigation for Phase 1.
- A composite fingerprint has two failure modes and both are accepted knowingly:
  a **false miss**, where harmless metadata churn invalidates a good cache and
  costs recomputation; and a **false hit**, where two different builds expose
  identical metadata and collide. False misses are cheap. False hits are the
  dangerous case and are the reason `fingerprint_source` is in the manifest —
  a result derived under `"composite"` or `"tag"` carries less provenance than
  one derived under `"digest"`, and Phase 2 must be able to tell them apart.
- Changing which fields feed the composite is a **breaking cache change**. The
  field list in the manifest is what makes that detectable rather than silent.
- A behavioural fingerprint (hash the response to a fixed canary prompt at
  `temperature=0`) was considered as a backend-agnostic substitute and rejected
  for Phase 1: it costs a startup inference call and is unsound on any backend
  that does not honour `temperature=0` deterministically.
- Prompts cannot narrate "today". Agent prompt templates must be written against
  the price window's last trading date from the outset; retrofitting this later
  would invalidate every cached entry.
