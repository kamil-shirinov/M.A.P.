# 0008 — Inference timeouts and the failure taxonomy

Status: Accepted · Date: 2026-08-09 · Amended 2026-08-10 · Phase 1

## Context

The inference server is local, and on 16 GB it loads model weights on demand and
unloads them to make room. A three-agent run swaps models three times. The first
call after a swap can sit for **30 seconds or more** before a single token
arrives, while a 12B is read from disk.

That makes timeouts a correctness concern, not a tuning detail. A default 5 s
timeout does not merely fail — it fails *constantly, on the normal path*, and it
fails in a way that looks like a bug in this codebase rather than a cold load in
the backend. Someone would then spend an afternoon debugging our HTTP layer.

The second half of the problem is naming. If "the server is not running" and "the
model is still loading" both surface as `InferenceError: timeout`, the two most
common operational states are indistinguishable, and the remedies are opposite:
start the server, versus wait longer.

## Options

1. **One timeout, one error type.** Simplest, and merges the two states that most
   need separating.
2. **One generous timeout, several error types.** Better, but a single value must
   be long enough for a cold 12B load, which means a genuinely dead server also
   takes ten minutes to report.
3. **Separate connect and read timeouts, with a typed error per failure mode.**

## Decision

**Connect and read timeouts are configured separately** —
`inference.connect_timeout_s` (default 10 s) and `inference.read_timeout_s`
(default 600 s).

The asymmetry is the point. The server is on `localhost`: if it will not accept a
socket within ten seconds, it is not running, and waiting longer learns nothing.
Once connected, the wait is entirely about how long weights and generation take,
which is minutes, not seconds.

**Five distinct error types**, and no two of them may be reachable from the same
situation:

| Failure | Type | What it means |
|---|---|---|
| No connection accepted | `InferenceUnreachableError` | The server is down or the URL is wrong |
| Connected, no response in time | `InferenceTimeoutError` | Almost always a cold model load |
| 404 on a completion | `ModelNotAvailableError` | That model is not on this server |
| Other non-2xx | `InferenceStatusError` | Carries status and body |
| 2xx, unparseable | `InferenceProtocolError` | Not the documented shape |

Two details that follow, and both were found by tests rather than by reasoning:

- **`ConnectTimeout` must be caught before `TimeoutException`.** It is both, and
  it means "no server", not "slow model". Exception ordering carries the
  distinction the whole ADR is about.
- **A 404 is translated to a missing model in `complete()`, not in the shared
  request path.** Translating it centrally is wrong twice over: a 404 on
  `/models` means the *endpoint* is absent rather than a model, and enriching the
  error by calling `list_models()` re-enters the same method and recurses until
  the stack is exhausted. The first version of this module did exactly that.

### Error enrichment must never re-enter the path that raised

Stated as a standing rule, because the recursion above is an instance of it rather
than a one-off slip.

Any call made to *improve an error message* — fetching the list of loaded models,
looking up a name, re-reading a file to quote it — is a call made at the worst
possible moment: something is already broken, and the state that broke it is still
in force. Two properties follow and both must hold.

**It must not re-enter the code path that raised.** If enrichment calls something
that can fail the same way, the failure recurses. Here, a 404 handler that called
a method whose 404 handler called it back.

**It must not be able to convert a clear failure into a worse one.** Enrichment is
strictly best-effort: every failure inside it is swallowed and the caller gets a
degraded message, never a different exception. An error path that itself raises
replaces a precise diagnosis with a stack trace pointing at the diagnosis
machinery.

Concretely, in this module: `_loaded_ids` catches `InferenceError` wholesale and
returns an empty tuple, and it is called only from `complete`, never from
`list_models`. Any future enrichment must satisfy the same two conditions.

`ModelNotAvailableError` re-queries discovery so the message names what *is*
loaded, because the usual cause is a naming difference between backends. That
enrichment is best-effort and swallows every `InferenceError`: it must never mask
the failure it is decorating.

## Consequences

- A dead server is reported in ~10 s. A cold load is allowed 10 minutes. Neither
  case can be mistaken for the other, and the timeout error's message names the
  cold load explicitly so the operator is not left guessing.
- `read_timeout_s = 600` is generous enough to hide a genuinely hung generation
  for ten minutes. That is the accepted trade: on this hardware, a slow first call
  is normal and a hung one is rare.
- The cache key includes the decode schema. That belongs to the key's definition
  rather than to this module, so it is **stated in ADR 0001** (amended 2026-08-10);
  `providers/keys.py` is only where it is implemented. Anyone reading ADR 0001 must
  see the complete key, or the canonical description of it is wrong.
- `request_key` is shared by the cache and the fake on purpose. A fixture recorded
  under one derivation and looked up under another is a silent, permanent miss.
- Nothing here names a vendor, and the fingerprint resolver never branches on
  which server it believes it is talking to — it asks which fields are present and
  composes from those. The vendor-string test covers the first half; the second is
  a review rule.
