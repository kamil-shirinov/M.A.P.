# 0022 — Guards that verify what their names claim

**Status:** accepted · **Date:** 2026-08-30 · **Builds on** [0005](0005-untrusted-text-and-document-identity.md), [0019](0019-corpus-execution-protocol.md), [0020](0020-context-window-and-truncation.md), [0021](0021-degeneration-retry.md)

## Context

`verify_freeze` refuses to start a corpus run when the live configuration has drifted
from the frozen record. It had been passing for weeks. **It compared the model alias
and nothing else** — one field of six.

An under-checking guard has no failure mode of its own. It just keeps returning green.
This one was found only because writing a freeze amendment meant reading the record by
hand, which is luck rather than process. So every guard, validator and assertion in
`src/` was audited with the same question: *what does the name imply, and what does the
code verify?*

**Fifteen gaps. Eleven guards confirmed sound.** The full table is [[../Guard Audit]].
What made the audit worth more than its findings is that the fifteen turned out to be
instances of three failures.

## The three shapes

**1 · Presence standing in for identity.** The check confirms something is there where
the name claims the *right* thing is there.

**2 · A declared number trusted instead of the thing measured.** The check compares
against a value someone wrote down and treats agreement with it as agreement with
reality. This is `verify_freeze` exactly, and it is [ADR 0020 §4](0020-context-window-and-truncation.md)
one layer up: the freeze held a number, the config held a different number, and nothing
ever put them side by side.

**3 · Scope narrower than the sentence.** The check is correct about a smaller thing
than its name describes.

## Decision

**Seven fixed now, eight recorded as stated limitations.** The split is by whether the
gap affects the integrity of the corpus run currently executing.

### Fixed before the restart — these affect the run itself

**#2 · The frozen record was never written down.** `freeze_version` appeared nowhere in
`src/`. `map evaluate` refused a band spanning two *code commits* while being blind to
one spanning two *freezes* — though the freeze governs sampling, truncation and corpus
membership. It is now stamped into every manifest and checked at scoring time.

**There is deliberately no `--allow-mixed-freeze`.** Mixed commits get an override
because a refactor between them can be genuinely harmless. Two freezes cannot be: they
mean two items were not asked the same question. An override there would be a flag whose
only use is to defeat the check.

**#1 · The trace guard verified presence, not identity.** Under the incident-22 bug, 56
runs had no trace and the 57th held every item's events. A file-exists check catches the
56 and passes the one that is *actually wrong* — the incident's own worst artifact.
`audit_trace` now bounds the event count: three agents each record at least one call, so
fewer than 3 is not a run, and more than 24 is more than one.

A count is a **weak** identity check, and worth naming as such. The strong one is a
`run_id` inside each event, which the trace format does not carry. Per-item wiring fixed
this at the source, so the bound is defence in depth — but a guard that would have passed
the incident it was written for is not a guard.

**#3 · The band failure threshold was per-invocation.** `health` restarted at zero on
every resume while the allowance stayed `ceil(0.02 × 356) = 8`. Three resumes tolerate 24
failures and never trip, and six nights involve restarts. The allowance is now seeded
from the ledger's resolved entries for this band.

Only *resolved* entries: a transient failure from an earlier pass is absent from
`resolved()` and will be retried, so counting it would charge the allowance for a failure
that may not survive the retry.

### Fixed during the run — no restart needed

**#8 · Sign was discarded when grounding numerals.** `abs()` throughout, so a fact of
`+46.3` grounded a justification's `−46.3`. On a forecast that is not a rounding
difference, it is the opposite claim. Now signed, with the tolerance on `abs(known)` so
it does not widen for negative values.

**The scope limit is now stated rather than implied.** The check reads justification
prose and nothing else — `price_return`, `annualised_vol` and `probability_weight`, the
numbers actually scored, are grounded against nothing by this or anything else. That is
partly principled: a forecast is supposed to state something the source did not, so
"grounding" a forecast figure is not well defined. But the name is broader than the
check, so the limit belongs in the README, not only in an audit note.

**#12 · `TrustedText` was the one type not pinned.** The construction-site guard pinned
`QuarantinedText` and `UntrustedText` and left seven `TrustedText` sites unasserted —
the **laundering** direction. `UntrustedText` marks something tainted, which is the safe
mistake; `TrustedText(document.text)` type-checks and promotes filed text into a slot
rendered without quarantine delimiters. All seven current sites are legitimate. A new one
would have reached CI green.

**#7 · The grammar probe ran an inverted test.** `set(payload) >= BRANCHES` accepted
supersets — but `additionalProperties: false` means an enforced grammar emits exactly
three keys, so **an extra key is evidence against enforcement** and was being scored as
enforcement. Now an exact match, at the top level and inside each branch, with the
expected fields read from `Scenario.model_fields` rather than restated.

**#10 · Status classification read English prose.** Four phrases in the response body
decided transient from terminal, so a server phrasing its refusal differently fell
through to `other`, was retried on every resume, and burned the allowance each time —
the ADR 0020 failure, reintroduced. It was also the vendor coupling `CLAUDE.md` §3
forbids, and the one ADR 0020 §4 had already removed *from the probe*: the lesson was
applied in one place and not the other.

**The split is now the status class.** A 4xx means this request is unacceptable and an
identical retry will be refused identically; a 5xx means the server is unwell, which a
retry may survive. The message match survives only to choose the more specific of two
*already terminal* names — the refinement shape ADR 0020 §4 settled on, where a parsed
message may sharpen a report but never decide one.

**The cost, stated.** A misconfigured server 400s every item, and up to five go terminal
before the consecutive-failure halt fires. Those five need their ledger lines removed by
hand. That is a bounded, visible price for not retrying the unretryable forever, and the
pre-flight context probe makes the likeliest cause unreachable.

## Stated limitations — known, documented, accepted for this run

Not open questions. Each is understood; none is being fixed before the corpus completes.

| # | Limitation |
| --- | --- |
| **4** | `_code_versions` has no band filter despite a docstring saying "of this band", so its counts span every band in the ledger. `_freeze_versions`, added here, *is* band-filtered — the inconsistency is deliberate and visible. |
| **5** | `degenerate_spread` measures `bullish − bearish`, a two-point range, where the docstring claims three-scenario distinctness. `base` a hair below `bull` passes. Strict ordering still guarantees all three differ. |
| **6** | `max_visible_tokens` is a declared bound nothing enforces; the chain validator's guarantee rests on it. Failure is loud (`PromptTooLargeError` at dispatch), not silent. |
| **9** | The truncation loop breaks at `tokens <= budget **or** at_floor` with no postcondition assertion, so "the invariant is enforced" overclaims below a ~664-token budget. `plan_truncation` and `truncate` also disagree on tail clamping for a document shorter than head+tail. Both regions are unreachable at the current 29,920-token budget. |
| **11** | `_format_errors` drops each error's `input` with the reasoning stated, and does not drop `loc` — which under `extra="forbid"` is the model's own key, reaching a trusted slot undelimited. Narrow: it needs the grammar to have failed first. |
| **13** | An exhibit absent from the frozen record warns and does not refuse; only missing and changed exhibits exit non-zero. |
| **14** | `allow_nondeterministic` records a *policy* under a name claiming a *result*. [[../Findings & Incidents#24]] measured that temperature 0 does not deliver reproducibility here. |
| **15** | `estimate_boundary` takes the first threshold crossing, not a sustained one, so one noisy month can set the cutoff that decides the corpus split. |

## Consequences

- `manifest_version` goes to **1.5.0**. Runs predating the field report
  `unknown (predates the field)`, which is honest and distinguishable from a run outside
  a corpus, where `freeze_version` is `None` because there is no freeze to record.
- **The three items already run lack `freeze_version`.** Left in the ledger they would
  make the band read as spanning two records and `map evaluate` would refuse it — which
  is the guard working. They are being cleared with the restart.
- `request_rejected` joins `FailureReason` and `TERMINAL_REASONS`.
- No freeze amendment. Nothing here changes what the models are asked or how they are
  sampled; `#8` changes a warning flag's sensitivity, and warnings are recorded rather
  than acted on.
- Two existing tests asserted the old behaviour and were rewritten rather than deleted:
  a non-context 400 staying transient, and a one-line file counting as a trace. Both now
  state why the rule moved.
