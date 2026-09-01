# 0030 — Adjudicating every code boundary in the clean band, before any score exists

**Status:** accepted · **Date:** 2026-08-31 · **Adjudicated before any forecast was scored** · **Builds on** [0019](0019-corpus-execution-protocol.md), [0026](0026-forecast-digest.md), [0029](0029-freeze-digest.md)

## Why now, and not at scoring time

The forecast digest ([ADR 0026](0026-forecast-digest.md)) refuses a band spanning two
code states and hands over the differing files so the decision is made on evidence.
The decision itself is still a judgement, and **the moment that judgement is made
determines how honest it is.**

At scoring time it stands between a person and a result they have spent two weeks
producing. *"These files look like plumbing"* is a much easier sentence to believe
under that pressure, and every incentive points one way. So it is made now, while
**no forecast has been scored anywhere**, and recorded with its reasoning.

Same argument as the ambiguous-band full-parity pre-commitment and the two sensitivity
partitions: the decision is cheap to make honestly before, and expensive after.

## The boundaries

Three code states produced the 169 completed items of the clean band:

| digest | commit | items |
| --- | --- | --- |
| `ef4c60c0c74a` | `318250f` | 119 |
| `fd5154ed7e9b` | `0d78326` | 14 |
| *none* | **dirty tree** | **208** |
| `65277e701c9a` | post-band re-runs | 9 |
| `24453884817e` | post-band re-run | 1 |

### The dirty figure moved twice, and the path is the record

Overwriting an intermediate value with a final one is the same instinct as deleting a
ledger line. All three are kept:

| figure | when | why it moved |
| --- | --- | --- |
| **34** | snapshot at item 136, mid-band | what the ledger held at the moment it was reported. Not wrong — just early. |
| **214** | band end, 349 complete | development continued against the live run for days after that snapshot. This is the honest peak. |
| **208** | now | ten items were re-run on a clean tree after the truncation correction; **six of them previously held dirty manifests**, and their replacement is the entire difference. |

**Nothing else changed between 214 and 208** — the only manifests written in that window
were the ten re-runs — so the six are arithmetically forced rather than inferred.

**The honest headline is 214 of 349, or 59% of the band as it stood when the band
finished.** 208 is the current figure only because correcting an unrelated defect happened
to clean six of them; it is not evidence that the practice was less bad than 214 says.

---

### Boundary 1 · `fd5154ed7e9b` → `ef4c60c0c74a` (15 → 120 items)

**Verdict: could not have changed what a model was asked.**

Three forecast-governing files differ, and all three changes are **additions
consumed only by the scoring side**:

| file | change | why it cannot reach a forecast |
| --- | --- | --- |
| `config/default.toml` | `earnings_dir = "var/earnings"` added under `[cache]`, with a comment | A new key. No existing key is modified, and it is read only by `build_earnings_calendar`. |
| `src/mapf/settings/loader.py` | `earnings_dir: Path` added to `CacheSettings` | A pydantic field with a default. Adding one changes no other field's value and no other section's validation. |
| `src/mapf/bootstrap.py` | `build_earnings_calendar` added; one import widened from `SqliteSymbolIndex` to `SqliteSymbolIndex, Throttle` | The function is called only by `map evaluate`. `build_run` — the only path a forecast takes through this module — is untouched. The single deletion in the whole diff is that import line. |

`build_earnings_calendar` exists to fit the earnings-multiplier **baseline**, which is
computed after the corpus from stored artifacts. It cannot reach an agent.

**The digest is over-including here by design, and that is not a defect.** ADR 0026
fixed its granularity at the file: it answers *did any file that can produce a forecast
change*, not *did the behaviour change*, because the second is undecidable without
running both. `config/default.toml` and `settings/loader.py` can absolutely change a
forecast — they carry every context window and sampling parameter — so they belong on
the governing side, and a diff confined to a new cache key is the price of that
correctness. **The digest is not wrong; it is coarse in the direction chosen on purpose.**

> **These 135 items are one stratum.**

---

### Boundary 2 · `ef4c60c0c74a` → the dirty group (120 → 34 items)

**Verdict: cannot tell. Reported as a separate stratum of 208 items.**

The items were produced from an **uncommitted tree**, so the files that executed are not
recoverable. This is the answer the record has to carry, and it is not the same as
"probably fine".

### Two claims that were being blurred, separated — and the second is falsified

The defence of this stratum rested on two sentences that were run together. They are
different claims and only one survives:

> **(a) The code behind these 208 items is not reconstructible from a commit.**
> True, unrecoverable, and stated. `code_version.dirty` records that the commit does not
> describe the working files.
>
> **(b) The forecast-governing surface was verified frozen at every launch.**
> **This is false as stated, and the truncation drift is what falsifies it.**
> `verify_freeze` compared prompts, model aliases and the execution seed. It did **not**
> compare the truncation block, so `chars_per_token_estimate` moved from 3.5 to 3.0
> under the same `head_tail_v1` label while every launch reported the freeze as matching
> ([[../Findings & Incidents#39]]). The surface was *partially* verified, and the part
> that was not verified is exactly the part that drifted.

**(b) was the reason (a) was tolerable**, so it has to be withdrawn as stated and
replaced with what is actually true:

> Prompts, model aliases and the execution seed were verified at every launch. Truncation
> was not, and it drifted — affecting **six of 351 completed items**, all identified, all
> re-run on the corrected basis. No other governing field is known to have moved, and
> none can be proved not to have.

**The stratum is large; the demonstrated forecast-relevant drift inside it is small and
has been corrected.** Both sentences belong in the record, and neither should be read
without the other.

What *is* adjudicable is the committed span `318250f → 4f57a82`, thirteen commits and
twelve forecast-governing files. Every path by which code can reach a model was checked
against that diff:

| checked | result |
| --- | --- |
| prompt templates under `src/mapf/prompts/` | **none changed** |
| `SamplingParams` — temperature, seed, `top_p`, `max_tokens`, penalty | **no field touched** |
| the request body built in `openai_compat` | **unchanged** |
| the cache key — `providers/keys.py`, `core/hashing.py` | **neither touched** |
| document handling in `data/exhibits.py` | exception **types** only, on the failure path; a successfully fetched document is byte-identical |
| `core/tokens.py`, `core/truncation.py` | **neither touched** |

The twelve files are recording (`pipeline/manifest.py`, `pipeline/run.py`,
`agents/base.py` capturing reasoning text), resume policy (`corpus/ledger.py`,
`corpus/runner.py`), execution order, error classification, digests and pre-flight
plumbing.

**None of that adjudication rescues the group.** The committed span is not what ran —
the process loaded its modules from a working tree that had uncommitted edits, and the
delta between them is unrecorded. I know what I was editing; that is memory, not
evidence, and this project does not accept memory as a substitute for a record
([[../Findings & Incidents#26]]).

So: **cannot tell**, and the group is reported separately rather than merged on a
plausible story. It is scoreable — its freeze digest was recoverable and its code
difference is covered by `--allow-mixed-code` — but it is never pooled with the 135
without the stratum being named.

The rule that stops this recurring is [ADR 0019](0019-corpus-execution-protocol.md) §8:
the band launches from a clean tree, and the runner now refuses otherwise.

---

## The four boundaries, named rather than counted

Four digests with counts is a record. Naming what differs is a report — and the whole
lesson of `head_tail_v1` is that an identifier which does not state what it covers hides
exactly this.

| digest | items | commit |
| --- | --- | --- |
| `fd5154ed7e9b` | 14 | `0d78326` |
| `ef4c60c0c74a` | 119 | `318250f` |
| *none — dirty* | 208 | `4f57a82` |
| `24453884817e` | 1 | `2388f11` |
| `65277e701c9a` | 9 | `4b91fed` |

**Boundary 1 · `0d78326 → 318250f`** — three files, all additions consumed only by
scoring: a cache key in `config/default.toml`, the settings field that reads it, and
`build_earnings_calendar` in `bootstrap.py`, which `map evaluate` calls and `build_run`
does not. **Cannot change a forecast.** *(Adjudicated above.)*

**Boundary 2 · `318250f → 2388f11`** — nineteen commits, thirteen files. Re-checked
against every path by which code reaches a model:

| | |
| --- | --- |
| prompt templates | **none changed** |
| `SamplingParams` fields | **none touched** |
| request body in `openai_compat` | **unchanged** |
| cache key — `keys.py`, `hashing.py` | **neither touched** |
| `data/exhibits.py` | comments and **exception types only**; a fetched document is byte-identical |
| `core/tokens.py` | **`CHARS_PER_TOKEN` 3.5 → 3.0** — the one forecast-relevant change |

The remaining files are recording, resume policy, digests and pre-flight plumbing.

**The ratio change is forecast-relevant only for documents it truncates, and no item in
the 119 or the 14 was truncated.** Zero, verified against the manifests: all nine
truncated items were re-run and now sit in `65277e701c9a`. For an untruncated document
the ratio decides only *whether* to cut, and it did not cut them at either value — so the
input is byte-identical across this boundary for every item that remains on the old side
of it.

**Boundary 3 · `2388f11 → 4b91fed`** — two files, purely additive: `rule_id()`, a computed
label, and the `verify_freeze` comparison that reads it. **A label and a startup check.
Neither can change a forecast.**

### Verdict

**Nothing forecast-relevant separates the four digest groups beyond the truncation ratio,
and that affects no item still on the old side of it.** The dirty 208 remain *cannot
tell*, unchanged.

## The result

| stratum | items | basis |
| --- | --- | --- |
| **adjudicated equivalent** | 135 | boundary 1 examined file by file; differences provably downstream |
| **unprovable** | 34 | produced from an uncommitted tree; reported separately, never pooled silently |
| **superseded** | 2 | BXP 2026-01-28, FCX 2026-01-22 — a different *freeze* digest, truncation changed, being re-run |

Two of the three are decisions taken with no result in view. The third is arithmetic.

## Consequences

- `map evaluate --allow-mixed-code` is the right call **for boundary 1 only**, and this
  document is what that flag is standing on. Passing it does not license pooling the 34.
- Any further boundary must be adjudicated the same way and appended here, **before**
  the band is scored. A boundary adjudicated after a score exists is not evidence.
- If a future boundary's verdict is *could have changed a forecast*, those items are a
  stratum too — the point of writing "cannot tell" down as a permitted answer is that
  the other two answers stay meaningful.
