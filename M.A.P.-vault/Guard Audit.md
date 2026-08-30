# Guard Audit — what each check's name implies, and what it verifies

Prompted by the `verify_freeze` drift ([[Findings & Incidents#26]]): that guard passed
convincingly for weeks while comparing **one field of six**. This is one pass over every
guard, validator and assertion in `src/`, asking the same question of each.

Ordered by how close the gap sits to a scored result. **Verified-sound entries are listed
too** — a check confirmed adequate is as useful as a gap found.

Nothing here is fixed. This is the map, not the work.

---

## The gaps

| # | Guard | Name implies | Actually verifies | Gap |
| --- | --- | --- | --- | --- |
| **1** | `_unauditable`, `_verify_artifacts` | this forecast is auditable | **a non-empty file exists at that path** | A trace belonging to a *different run* passes both. Under the incident-22 bug the first item's `trace.jsonl` held all 57 items' events — present, large, and wrong. Both guards would green-light it. |
| **2** | *(absent)* | — | — | **Nothing records `freeze_version` in a manifest**, and nothing checks it at scoring time. `evaluate` refuses a band spanning two *code* commits and is blind to one spanning two *freezes* — though the freeze governs sampling, truncation and corpus membership. |
| **3** | `max_band_failure_rate`, "2% of 356" | a band-wide failure ceiling | **a per-invocation ceiling against a band-wide denominator** | `health` restarts at zero on every resume while `allowance` stays `ceil(0.02 × 356) = 8`. Three resumes tolerate 24 failures and never trip. |
| **4** | `_code_versions` — *"commits that produced the completed runs of this band"* | commits for **this band** | commits across **every band in the ledger** | No band filter, though `_unauditable` two functions above has one. Counts are wrong, and an ambiguous-band commit can refuse a clean-band score. |
| **5** | `degenerate_spread` — *"three scenarios within a hair of each other are not three scenarios"* | the three scenarios are distinct | **`bullish − bearish` exceeds a floor** | A two-point range, not three-point distinctness. `base` at +9.99% against `bull` at +10.0% passes cleanly: strict ordering holds and the outer spread is wide. |
| **6** | `_each_output_fits_the_next_input` — *"every agent's maximum output must fit the next input"* | maximum output fits | **`max_visible_tokens` fits — a number nothing enforces** | `visible_budget` is read only by this validator. No runtime cap holds the analyst to 4,096 visible tokens. Fails loudly at `_assert_fits` rather than silently, so the cost is bounded — but the startup guarantee is not one. |
| **7** | `probe_grammar` → `"enforced"` | the grammar constrained the sampler | **the reply is JSON whose keys are a superset of the three branches** | `>=` accepts supersets. With `additionalProperties: false` a *correct* grammar emits exactly three keys, so a superset is positive evidence the grammar was **not** enforced — and it is scored as enforcement. Nothing checks the nested fields, bounds or lengths. |
| **8** | `ungrounded_numerals` | figures in the output trace to a fact | **figures in the `justification` prose match a fact within 1%, ignoring sign** | Two holes. `abs()` throughout, so a fact of `+46.3` grounds a justification's `−46.3`. And it reads only the prose — `price_return`, `annualised_vol` and `probability_weight`, the numbers that are actually scored, are never grounded against anything. |
| **9** | truncation — *"the invariant is enforced, not trusted"* | the result is under budget | **under budget, or at the shrink floor** | `if tokens <= budget or at_floor: break`, and no postcondition assertion. Below a ~664-token budget it returns an oversized document with `applied=True` and no error. Separately, `plan_truncation` caps the tail so head+tail ≤ original and `truncate` does not, so for a document shorter than head+tail the gate and the runtime disagree and the "truncated" text contains duplicated content. Both regions are unreachable at the current 29,920-token budget — the docstring is what overclaims, not the behaviour. |
| **10** | `_classify_status` | context overflow is terminal | **an HTTP 400 whose body contains one of four English phrases** | Vendor-specific prose matching in application code — what `CLAUDE.md` §3 forbids and what [[decisions/0020-context-window-and-truncation\|ADR 0020 §4]] deliberately moved the probe *away* from. A server phrasing its 400 differently falls through to `other`, which is **transient**, so it is retried and consumes the allowance: exactly the failure ADR 0020 exists to prevent. |
| **11** | `_format_errors` — *"only `loc` and `msg`… never from the rejected input"* | no model text reaches the trusted slot | **`input` is excluded. `loc` is not.** | Sound on the channel it names. But under `extra="forbid"` the `loc` of an extra-field error **is the model's own key**, which lands in `TrustedText` and is interpolated into the repair prompt undelimited. Narrow — it needs the grammar to have failed first — but the repair loop is precisely the path where it has. |
| **12** | `test_construction_sites` — *"there must be exactly one way to produce `QuarantinedText`"* | the taint system's construction sites are pinned | `QuarantinedText` and `UntrustedText` are pinned | **`TrustedText` is not pinned at all** — 7 sites, none asserted. It is the laundering direction: `TrustedText(document.text)` type-checks, and no test would notice a new one. All 7 current sites are safe; #11 is the one that is subtle. |
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

## What the shape of these has in common

Three recurring forms, worth recognising before writing the next guard:

1. **The check verifies presence where the name claims identity.** #1 — a file exists where "this run's audit trail" is claimed. #13 — bytes match for items we thought to ask about.
2. **The check trusts a declared number instead of measuring the thing.** #6 — `max_visible_tokens` is an assumption the validator treats as a limit. #14 — a configured temperature stands in for a measured property. This is the `verify_freeze` failure exactly: *the freeze held a number, the config held a different number, and nothing put them side by side.*
3. **The check's scope is narrower than its sentence.** #4 — "this band" without a band filter. #3 — a band rate enforced per invocation. #5 — a range measured where distinctness is claimed. #9 — an invariant with an unasserted escape.
