# Guard Audit — what each check's name implies, and what it verifies

Prompted by the `verify_freeze` drift ([[Findings & Incidents#26]]): that guard passed
convincingly for weeks while comparing **one field of six**. This is one pass over every
guard, validator and assertion in `src/`, asking the same question of each.

Ordered by how close the gap sits to a scored result. **Verified-sound entries are listed
too** — a check confirmed adequate is as useful as a gap found.

**Status.** Seven are fixed — see [[decisions/0022-guard-scope|ADR 0022]]. Each fixed
row below is struck through and carries what it now verifies. The remaining eight are
**stated limitations**, not open questions: their behaviour is known, documented, and
accepted for this run.

---

## The three shapes

The fifteen findings below are instances of three failures, not fifteen unrelated
ones. The shapes are the transferable part — recognise them before writing the next
guard, not after.

### 1 · Presence standing in for identity

The check confirms *something is there* where the name claims *the right thing is
there*. A trace guard that verifies a non-empty file exists at a path passes a file
holding another run's events — and that was the incident's own worst artifact.

> Instances: **#1** (trace), **#13** (exhibits).

### 2 · A declared number trusted instead of the thing measured

The check compares against a value someone wrote down, and treats agreement with it
as agreement with reality. This is the `verify_freeze` failure exactly, and it is
the same move as [[decisions/0020-context-window-and-truncation|ADR 0020 §4]] one
layer up: *the freeze held a number, the config held a different number, and nothing
ever put them side by side.*

> Instances: **#6** (`max_visible_tokens`), **#14** (`temperature == 0` standing in
> for reproducibility), and the incident that prompted the audit.

### 3 · Scope narrower than the sentence

The check is correct about a smaller thing than its name describes. "This band"
without a band filter; a band rate enforced per invocation; a range measured where
distinctness is claimed; an invariant with an unasserted escape.

> Instances: **#3**, **#4**, **#5**, **#8**, **#9**, **#15**.

Two findings sit outside the taxonomy and are simpler: **#7** is an inverted test —
evidence *against* enforcement scored as enforcement — and **#10**, **#11**, **#12**
are channels a guard's own stated reasoning did not enumerate.

---

## The findings

The last column is the **gap** for open rows and **what it now verifies** for fixed ones.

| # | Guard | Name implies | Actually verifies | Gap / status |
| --- | --- | --- | --- | --- |
| **1** | `_unauditable`, `_verify_artifacts` | this forecast is auditable | **a non-empty file exists at that path** | **FIXED** — `audit_trace` bounds the event count: fewer than 3 is not a complete run, more than 24 is more than one. A count is a weak identity check; the strong one is a `run_id` inside the events, which the format does not carry. |
| **2** | *(absent)* | — | — | **FIXED** — `RunManifest.freeze_version`, stamped by the corpus runner, and `map evaluate` refuses a band spanning two records with **no override flag**. |
| **3** | `max_band_failure_rate`, "2% of 356" | a band-wide failure ceiling | **a per-invocation ceiling against a band-wide denominator** | **FIXED** — the allowance is seeded from the ledger's resolved entries for this band, so it is cumulative across resumes. |
| **4** | `_code_versions` — *"commits that produced the completed runs of this band"* | commits for **this band** | commits across **every band in the ledger** | No band filter, though `_unauditable` two functions above has one. Counts are wrong, and an ambiguous-band commit can refuse a clean-band score. |
| **5** | `degenerate_spread` — *"three scenarios within a hair of each other are not three scenarios"* | the three scenarios are distinct | **`bullish − bearish` exceeds a floor** | A two-point range, not three-point distinctness. `base` at +9.99% against `bull` at +10.0% passes cleanly: strict ordering holds and the outer spread is wide. |
| **6** | `_each_output_fits_the_next_input` — *"every agent's maximum output must fit the next input"* | maximum output fits | **`max_visible_tokens` fits — a number nothing enforces** | `visible_budget` is read only by this validator. No runtime cap holds the analyst to 4,096 visible tokens. Fails loudly at `_assert_fits` rather than silently, so the cost is bounded — but the startup guarantee is not one. |
| **7** | `probe_grammar` → `"enforced"` | the grammar constrained the sampler | **the reply is JSON whose keys are a superset of the three branches** | **FIXED** — exact key match at the top level *and* inside each branch, with the expected fields read from `Scenario.model_fields` rather than restated. |
| **8** | `ungrounded_numerals` | figures in the output trace to a fact | **figures in the `justification` prose match a fact within 1%, ignoring sign** | **FIXED** — numerals are signed, and the tolerance uses `abs(known)` so it does not widen for negatives. The prose-only scope is now stated in the docstring and the README. |
| **9** | truncation — *"the invariant is enforced, not trusted"* | the result is under budget | **under budget, or at the shrink floor** | `if tokens <= budget or at_floor: break`, and no postcondition assertion. Below a ~664-token budget it returns an oversized document with `applied=True` and no error. Separately, `plan_truncation` caps the tail so head+tail ≤ original and `truncate` does not, so for a document shorter than head+tail the gate and the runtime disagree and the "truncated" text contains duplicated content. Both regions are unreachable at the current 29,920-token budget — the docstring is what overclaims, not the behaviour. |
| **10** | `_classify_status` | context overflow is terminal | **an HTTP 400 whose body contains one of four English phrases** | **FIXED** — classified by status class: 4xx terminal (`request_rejected`), 5xx transient. The message match survives only to choose the more specific of two terminal names. |
| **11** | `_format_errors` — *"only `loc` and `msg`… never from the rejected input"* | no model text reaches the trusted slot | **`input` is excluded. `loc` is not.** | Sound on the channel it names. But under `extra="forbid"` the `loc` of an extra-field error **is the model's own key**, which lands in `TrustedText` and is interpolated into the repair prompt undelimited. Narrow — it needs the grammar to have failed first — but the repair loop is precisely the path where it has. |
| **12** | `test_construction_sites` — *"there must be exactly one way to produce `QuarantinedText`"* | the taint system's construction sites are pinned | `QuarantinedText` and `UntrustedText` are pinned | **FIXED** — `TrustedText`'s 7 sites are pinned, plus a test that no module outside `agents/` mints both types. |
| **13** | `exhibits   all N match the frozen hashes` | the corpus is unchanged at source | **the fetched bytes match, for items in the plan** | Two things. `unrecorded` (fetched an accession the freeze does not name) prints yellow and **does not refuse** — only `missing` and `changed` exit non-zero. And there is no HTTP cache anywhere: this re-fetches from EDGAR every time, so it is a genuine source check but costs 712 throttled requests per `--check`. |
| **14** | `_enforce_determinism`, `allow_nondeterministic` | this run is reproducible | **`temperature == 0.0` was configured** | Now known false — [[Findings & Incidents#24]] measured 2 of 5 replays byte-identical. A manifest reading `allow_nondeterministic: false` asserts a property the backend does not provide. The field records a *policy*, and its name claims a *result*. |
| **15** | `estimate_boundary` — *"first month where hedging takes over"* | the boundary where knowledge stops | **the first month whose rate crosses a threshold once** | `next(...)` takes the first crossing, not a sustained one. One noisy month sets the cutoff, and the cutoff decides the corpus split. |

---

## Verified sound

Checked and adequate for what they claim.

| Guard | Why it holds |
| --- | --- |
| `quarantine` | The fixpoint loop exits only when a full pass finds no marker, and the replacement is strictly shorter than any marker, so termination and the postcondition are both structural. The `else` branch raises rather than returning unsanitised text. |
| `FilePromptStore.render` | Checks **both** directions — a slot supplied but absent from the template, and a slot present but unsupplied — plus trusted/untrusted overlap. Role markers are parsed before substitution and `re.sub` never rescans, so untrusted text cannot open a message or expand a second slot. |
| `ScenarioSet` validators | Weights sum to 1 within 1e-6; returns strictly ordered `bearish < base < bullish`. Both span fields, which is exactly what the grammar cannot express, and both raise rather than coerce. |
| `Bar`, `PriceWindow`, `DividendWindow` | OHLC containment, strictly-increasing dates, and the `known`/detail coupling that stops `ex_dates: ()` reading as "no dividends". |
| `decode_schema` | Strips prose but recurses into `properties`/`$defs` **by name**, so a field legitimately called `title` survives. Constraints are untouched. |
| `request_key` | Hashes fingerprint + messages + decode schema + full sampling + attempt. The schema is folded in deliberately, since the grammar is part of the request. |
| `_format_errors` (on `input`) | Excludes the offending value with the reasoning stated. Sound on the channel it names — see #11 for the one it does not. |
| `_budgets_fit_their_context` | Requires strict headroom (`max_tokens + 512 > context`) rather than mere inequality. |
| `split_passes`, `require_finished` | Interleaved by position so a pass is a spread sample; `status_of` reads the ledger only, never the filesystem. |
| `verify_freeze` | **Was #1 of this list.** Now compares every field the frozen record names, in both directions, and reports all mismatches at once. |

---
