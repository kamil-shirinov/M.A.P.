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

**Correction, 2026-09-01: the dirty stratum is 208, not 34.** The figure reported while
the band was running was a snapshot at item 136; development continued against the live
run for days afterwards. **59% of the completed band was produced from an uncommitted
tree** — not 9%. Recorded as measured.

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
