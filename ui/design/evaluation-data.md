# The evaluation screen — what the export can support

For CD, before any design. This is a profile of the real export, measured on
2026-09-24, in the same form as `runs-screen-data.md`. Every number below was
computed from the files a page would read; where a number is quoted from the
project's own record rather than computed, it says so.

**The export this describes:** `export_version` 1.2.0, freeze 2.6.0, code `b0596c4`,
exported 2026-09-17, price vintage 2026-09-05.

**The short answer.** The export carries **one** evaluation artifact: a single
scoring pass over the **clean band of the development half**, 175 items, shipped
twice. Everything else that has been measured on this project — the holdout, the
ambiguous band, the four-arm ablation, the calibration fit — is either absent by
design and unrecoverable, or sits outside the export in M.A.P.

---

## 1. What is in the export

| File | Load | Size | What it is |
|---|---|---|---|
| `scores/clean.dev.2026-09-05.1997f7352e47.json` | lazy | 133.5 KB | the scoring pass, code-identified |
| `scores/clean.dev.2026-09-05.dirty.json` | lazy | 133.5 KB | the same pass, from an unidentifiable tree |
| `manifest.json` → `scores.records` | eager, 1.9 KB | — | both records' identity |
| `manifest.json` → `scores.absent` | eager | — | why there is no holdout record |

**The two records hold identical items and identical summaries.** They differ in
exactly two fields: `commit` (`83370f6` against `d8c57c3`) and `forecast_digest`
(a digest against `null`). Same measurement recorded twice under different code
states — not two results. The contract's rule is to prefer the record whose
digest is non-null and to say the other exists; never average them.

### The record

```
band          "clean"            split       "dev"
n             175                vintage     "2026-09-05"     (the price snapshot)
scored_on     "2026-09-09"       freeze_version  "2.6.0"
unscored      { "SpotDriftError": 3 }
commit, forecast_digest, freeze_digest
summaries     { "crps": [3 lines], "log score": [3 lines] }
items         [175]
```

### Where the 175 come from

The journal holds 701 panel runs. Of those, **178 are clean band and belong to a
development-split ticker**; 3 SCCO items were refused by the spot-drift guard, and
**178 − 3 = 175**. That arithmetic is the whole relationship, and it is worth
printing on the screen, because "175" next to "779 runs" invites the reader to
divide one by the other.

The 175 items cover **59 tickers and 66 dates**, all 5-session, all clean band.

**The join still does not exist.** An item carries `as_of`; a run carries
`anchor_date`. They coincide for **161 of the 175** — the other 14 are Saturdays
and Good Friday. A screen may not attach a score to a run, and this is the
measured reason.

---

## 2. What an item carries

Eighteen fields per item, and they are richer than the summaries suggest:

| Field | What it is |
|---|---|
| `ticker`, `as_of`, `band`, `horizon_days` | which forecast |
| `day_index` | the trading day as an integer, 9505 to 9715 — what the clustering was done on |
| `provider`, `adjustment` | where the outcome price came from |
| `realised_return` | the outcome, a **log** return |
| `map_sigma` | the stated dispersion, 0.026 to 0.089 |
| `map_pit` | the PIT value — **yes, per item, all 175** |
| `map_probability_up` | 0.369 to 0.631, median 0.513 |
| `map_crps`, `map_log_score`, `map_brier` | M.A.P.'s three scores |
| `baseline_crps`, `baseline_log_score`, `baseline_brier` | each an object keyed by **all three baselines**: `random_walk`, `garch`, `earnings_scaled_random_walk` |
| `earnings_multiplier` | 0.389 to 2.78, the scaling the third baseline applies |

So the export carries **per-item, per-baseline scores** — 175 × 4 models × 3
rules. That is enough for distributions, scatters and win rates, not only for the
six headline lines.

---

## 3. What recomputes, and what is prose only

**Recomputes exactly** (checked against the project's published figures):

| Statistic | Computed from the items | Published |
|---|---|---|
| Calibration ratio | RMS(`map_sigma`) / RMS(`realised_return`) = **0.7331** | 0.733 |
| Directional accuracy | 87 of 175 = **49.7%** | 49.7%, 87 of 175 |
| PIT mean | **0.4891** | 0.4893 |
| CRPS against the random walk | mean 0.03179 against 0.03016 = **worse by 5.4%** | worse by 5.4% |

**Prose only — the page cannot rebuild these.** Every interval in the summaries
comes from a cluster-robust moving-block bootstrap: 10-day blocks, a fixed seed,
a draw count. None of the three is in the export, and neither is the mapping from
`day_index` to the **18 date clusters** the lines quote. The summaries are six
strings, and a screen shows them **verbatim**:

```
M.A.P. vs random_walk: worse by 5.4% [+0.00071, +0.00278], n=175, 18 date clusters
M.A.P. vs garch: indistinguishable at n=175 (18 date clusters), interval
  [-0.00035, +0.00220] spans zero — this is not evidence of no difference
```

**A caution about recomputing tail counts.** This record gives |z| > 2.5 on 13
items and |z| > 3 on 7. The vault quotes 11 and 7 for development, computed on 178
items before the SCCO exclusions. Both are right about their own sample. If the
screen prints its own count it has to name the sample, or it will look like it
contradicts the write-up.

### Two conventions the screen must state

1. **The log score is stored so that lower is better.** M.A.P. −1.3786 against the
   random walk's −1.5826 means M.A.P. is *worse*, by 12.9%. A chart that sorts
   "higher is better" inverts the result.
2. **Brier is one comparison, not three.** All three baselines score exactly
   0.25 on every item, by construction — they set drift to zero and predict
   P(up) = 0.5. M.A.P. scores 0.25193, marginally worse than a coin. There is no
   Brier line in `summaries`; it would have to be computed and labelled as such.

---

## 4. The holdout

`manifest.scores.absent` carries one entry, and it is a stated fact rather than a
gap: the holdout was scored once, its per-item scores were printed once and never
persisted, and `map evaluate --split holdout` is refused before computing
anything once the spend is recorded. **This is unrecoverable, by design.**

`what_survives` names two things: the calibration coefficients and their fitted
form, and the band, item count, date, commit, freeze version and price vintage.
Those live in `corpus/holdout_spend.jsonl` in M.A.P. — **which the export does not
carry** (see §5). One further limit, recorded as M.A.P. Findings #57: the
holdout's comparison against the three baselines survives as a sentence in five
documents and as a figure nowhere, so no screen can show it as a number.

---

## 5. What is not in the export

| | Where it is | Absent by design? | What exporting costs |
|---|---|---|---|
| Holdout per-item scores | nowhere | **yes** — unrecoverable | nothing to export |
| Holdout spend record | `corpus/holdout_spend.jsonl`, tracked, 1 line | no | trivial: copy one file |
| Ambiguous band | not scored into a record | no | one scoring run + one 133 KB file |
| Ablation's 786 runs | `var/ablation/{A,B,C,D,control,probe}`, 56 MB | no | a second read path; ~650 KB of rows |
| The 22 pre-registrations | `refs/notes/commits`, 121,186 bytes | no | a git read; the proof does not travel |
| Stratum membership | not per item anywhere | no | a new field per item; export shape bump |

**The holdout spend record** is one tracked JSON line holding `a = −0.0757`,
`b = 1.3305`, the fitted form, what it was fitted on, 173 items, the dates and the
identity stamps. Exporting it is the cheapest item on this list and it is the only
way a screen could state the holdout's *terms* — never its numbers, which do not
exist.

**The ambiguous band** is the interesting one. It is not the holdout, so it can be
scored again: `map evaluate --band ambiguous --split dev` already exists, and the
journal holds 350 ambiguous panel runs. Today the leakage result — clean 0.0318
against ambiguous 0.0335 — can only be quoted. One scoring run would turn it into
two exported records a screen could compare directly.

**The ablation** lives in the same shape as `runs/` (each run a directory with
`forecast.json`, `manifest.json`, `trace.jsonl`), in six arm directories holding
801 entries. The journal's schema is already ready for it: every row carries an
`arm` field, null on all 779. Exporting the runs is mechanical. But the runs are
forecasts, not results: the **four-arm comparison itself is not an artifact** —
it lives in git notes 15 to 22 and the Timeline. Showing ablation results honestly
would need a scoring pass per arm, persisted, which does not exist yet.

**The pre-registrations** are one note of 121,186 bytes on commit `ad71b13`, and a
`git clone` does not fetch notes at all. `map export` could shell out to git and
write them as text — there is precedent, since `map evaluate` reads past frozen
records with `git show`. The cost is not the code: **a copy is not the evidence.**
What makes the records pre-registrations is the commit dates on the notes ref, and
a JSON copy cannot carry that. If they are exported, the page has to say the text
came from the notes and that the ordering is checkable only in git.

**Stratum membership** — which items are dirty-tree, truncated, or degeneration
retries — is not a per-item flag anywhere. `frozen.json` holds the corpus-level
settings, not per-item outcomes. The export carries only `unscored`, and today
that is `{ "SpotDriftError": 3 }`. A stratum table means adding a field per item in
M.A.P.'s scoring record, which changes the record's shape.

---

## 6. What one screen could honestly show

All of this, from the one record, with no new export:

- **What was measured, and on what.** 175 items = 178 clean/dev panel runs − 3
  refused by the spot-drift guard; 59 tickers, 66 dates, one band, one split, one
  horizon. The relationship to the 779 runs, stated rather than left to inference.
- **The six comparisons, verbatim**, two rules against three baselines, with their
  intervals as written — and the mean values beside them, which recompute.
- **Calibration**: the ratio at 0.733, recomputed on the page and agreeing with the
  record; a PIT histogram over all 175 items; the tail counts with their sample named.
- **Direction**: 87 of 175, and the P(up) span of 0.369 to 0.631 that explains it —
  against a Brier of 0.25 that all three baselines score by construction.
- **Per-item distributions**: 175 points of `map_crps` against each baseline's, or
  `map_sigma` against |realised| — the shape behind the headline percentages.
- **Which record is being shown**, and that a second exists from an unidentifiable
  tree.
- **Four absences, stated**: the holdout (never persisted, unrecoverable), the
  ambiguous band (scoreable, not exported), the ablation (outside the export), and
  the intervals (prose, not rebuildable).

What it must not do: divide 175 by 779, print a holdout figure, recompute an
interval, attach a score to a run, or sort the log score as if higher were better.

---

## 7. Load cost

`manifest.json` (1.9 KB) names both records and the holdout absence; the screen
needs **one** 133.5 KB record. Nothing else — universe.json (7.5 KB) only if rows
want company names. The journal's 649.2 KB is not needed on this screen: the
scoring record carries its own tickers and dates.
