# The `map export` contract

What `map export --out <dir>` writes, field by field, for a front end reading it as
static assets. No server runs behind these files.

```bash
uv run map export --out ./export          # write it
uv run map export --out ./export --check  # has anything moved since?
```

`export_version` is **1.1.0**. It is the shape of these files, not the age of the data
— read it first and refuse a version you do not know. Every size below is at the
current corpus (120 companies, 709 filings, 779 runs) and will grow with it.

---

## 1. Files

| Path | Load | Size | Rows |
|---|---|---|---|
| `manifest.json` | **eager, first** | 1.7 KB | — |
| `universe.json` | **eager** | 7.5 KB | 120 |
| `corpus.json` | **eager** | 108.8 KB | 120 |
| `runs/by_source/corpus.json` | **eager** | 0.0 KB | 0 |
| `runs/by_source/edgar.json` | **eager** | 0.0 KB | 0 |
| `runs/by_source/news.json` | **eager** | 0.0 KB | 0 |
| `runs/by_source/unknown.json` | **eager** | 632.8 KB | 779 |
| `symbols.json` | lazy | 864.5 KB | 10,398 |
| `filers.json` | lazy | 1,234.4 KB | 8,001 |
| `prices/<TICKER>.json` | lazy, per company | 2,074.9 KB total · 17.3 KB median | 120 files |
| `scores/<band>.<split>.<vintage>.<digest>.json` | lazy | 133.5 KB each | 2 files |

**Eager total 0.75 MB. Whole export 5.19 MB.**

Load `symbols.json` on the first keystroke in search, not at boot: 120 companies have
something to show and 10,398 do not. `filers.json` answers "does this ticker's filer
publish earnings 8-Ks at all" and is only needed once a search returns something outside
the corpus.

**There is no combined runs file, and this is deliberate.** The four `runs/by_source/`
files mirror the four populations the library keeps separate in memory; a consumer that
wants all of them must fetch four and concatenate on purpose. Do not create a merged
array and then filter it — see §3.

---

## 2. File by file

### `universe.json` — the companies with anything to show

```json
[{ "ticker": "AAPL", "name": "Apple Inc.", "split": "holdout" }]
```

| Field | Type | Claim |
|---|---|---|
| `ticker` | string | Symbol as the frozen corpus records it. |
| `name` | string \| **null** | Company name from the SEC symbol index. **null** = the index was not exported (see §5). Not "unnamed". |
| `split` | `"dev"` \| `"holdout"` | Which half of the panel this company belongs to, fixed at selection and frozen. A company is in the same split in both bands. |

### `corpus.json` — every filing the corpus holds

```json
[{ "ticker": "AAPL", "name": "Apple Inc.", "cik": 320193, "split": "holdout",
   "filings": [{ "filed": "2025-05-01", "accession": "0000320193-25-000055",
                 "band": "ambiguous", "split": "holdout",
                 "runs": ["bb1e69f6-9ea9-47f4-aae0-f43e3dc8c76e"] }] }]
```

| Field | Type | Claim |
|---|---|---|
| `cik` | int \| null | SEC filer id. |
| `filings[].filed` | date | The date the 8-K was filed. **Not** the date a forecast opens — that is the day after. |
| `filings[].accession` | string \| **null** | SEC accession number. **null** = this corpus record predates accession storage. Not "unknown filing". |
| `filings[].band` | `"clean"` \| `"ambiguous"` | `clean` is after the models' training cutoff; `ambiguous` is before it and exists to measure leakage. |
| `filings[].runs` | string[] | Run ids the ledger maps to this filing. **May be empty.** |

**709 filings across 120 companies. 8 have an empty `runs` array** — items that failed
terminally. Show them as held-but-not-run. A company page that lists only filings with
runs shows 701 and misstates the corpus.

### `runs/by_source/*.json` — the run journal

```json
{ "run_id": "46cf0ac0-…", "ticker": "AAPL",
  "anchor_date": "2026-08-13", "anchor_spot": 302.9849853515625, "horizon_days": 5,
  "scenarios": [{ "name": "bullish", "probability_weight": 0.25,
                  "price_return": 0.012, "annualised_vol": 0.20 }, …],
  "document_source": "unknown", "freeze_version": null, "arm": null,
  "document_is_frozen_exhibit": false, "corpus_relation": "outside_corpus",
  "ledger_item": null,
  "outcome": { "trading_date": "2026-08-20", "close": 311.29998779296875,
               "provider": "yfinance", "adjustment": "split_adjusted",
               "snapshot": "2026-09-05", "retrieved_on": "2026-09-09" },
  "outcome_status": "closed" }
```

| Field | Type | Claim |
|---|---|---|
| `run_id` | uuid | Directory name under `runs/`. |
| `anchor_date` | date | The **trading session the forecast opened from** — the bar `anchor_spot` was read at. Not the run's wall clock, and not the filing date. |
| `anchor_spot` | float | The close the forecast was produced against. Float32 from the provider, so display to 2dp; the stored value is exact. |
| `horizon_days` | int | Horizon in **trading** sessions, not calendar days. |
| `scenarios` | array of 3 | Always `bullish`, `base_case`, `bearish`, in that order. `probability_weight` sums to 1.0 (±1e-6). `price_return` and `annualised_vol` are **decimal fractions** — `0.012` is 1.2%, not 1.2. |
| `document_source` | see §3 | Where the document came from, **as the writer recorded it**. |
| `freeze_version` | string \| null | Which frozen record governed the run. null = outside a corpus, *or* predates the field. Ambiguous by design — use `corpus_relation`. |
| `arm` | string \| null | Experimental arm. See §6. |
| `document_is_frozen_exhibit` | bool \| null | Whether this run's document hash matches an exhibit in `frozen.json`. **null = not checked.** |
| `corpus_relation` | see §3 | Where the run stands to the pre-registered panel. **Use this, not the two fields above.** |
| `ledger_item` | object \| null | `{ticker, band, filing_date}` — present only when `corpus_relation` is `ledger_item`. |
| `outcome` | object \| null | The realised close. Present only when `outcome_status` is `closed`. |
| `outcome_status` | see §4 | Why there is or is not an outcome. |

**`ledger_item.filing_date` is carried, never derivable.** A corpus forecast is dated the
day *after* the filing it reads. Only **66 of 701** have `filing_date == anchor_date`.
Reconstructing it from the anchor is wrong on 635 runs, silently. Use the field.

**Nothing in this file compares a forecast to its outcome, and a UI should not either.**
There is no error, no return, no hit rate — by design (ADR 0035). `runs/` is a population
defined after the fact by curiosity, retries and interrupted evenings; an accuracy figure
over it would be real arithmetic on an unreal sample. Scores come from `scores/`.

### `prices/<TICKER>.json` — one series per company

```json
{ "ticker": "AAPL", "provider": "yfinance", "adjustment": "split_adjusted",
  "snapshot": "2026-09-05",
  "bars": [["2024-07-31", 222.0800018310547], …, ["2026-09-03", 328.2099914550781]] }
```

`bars` is `[date, close]` pairs, ascending, from the **longest window the pinned vintage
holds** — median 526 bars, about two years. Closes only; there is no OHLC here.

`snapshot` is the vintage, and it matters: these are not live prices. The same file read
next month says the same thing. Show the snapshot date near any chart.

**There is no "current price" anywhere in this export and there cannot be.** Both
providers serve daily bars, so the newest value is a close on a trading date — three days
old on a Monday. Label it `last close on <date>`, never "current".

### `symbols.json` — the searchable index

```json
[{ "ticker": "NVDA", "name": "NVIDIA CORP", "exchange": "Nasdaq", "cik": 1045810 }]
```

10,398 SEC-registered tickers. `exchange` may be null. Presence here means "this symbol
exists", nothing more — most have no filings, no runs and no prices.

### `filers.json` — which filers publish earnings 8-Ks

```json
{ "cik": 1750, "tickers": ["AIR"], "fetched_on": "2026-09-09", "block": "recent",
  "status": "ok", "item_202_in_recent": true, "count": 51, "most_recent": "2026-07-21" }
```

| Field | Type | Claim |
|---|---|---|
| `cik` | int | The filer. One row per filer, **not per ticker** — 8,001 rows cover 10,398 tickers because share classes share a CIK. |
| `tickers` | string[] | Every ticker on this filer. Join to `symbols.json` on these. |
| `item_202_in_recent` | bool | **Only present when `status` is `"ok"`.** |
| `count` | int | Item 2.02 filings found in the recent block. |
| `most_recent` | date \| null | Newest one found. null when `count` is 0. |
| `fetched_on` | date | When this row was walked. Per row, because a resumed walk spans days. |
| `status` | `"ok"` \| `"http_404"` \| `"http_403"` \| `"malformed"` \| `"request_failed"` | 7,998 ok, 3 `request_failed` retried and superseded. |

**`item_202_in_recent` is not "has ever filed".** It reads only the submissions *recent*
block — roughly a year for an active filer. A company that stopped reporting three years
ago reads `false`. That is a usable pre-screen answer and a false statement about
history, so a UI must say **"no recent earnings 8-K"**, never "never filed".

The funnel this supports: **10,398 tickers → 7,998 filers → 4,325 with a recent Item 2.02
(54.1%) → 5,309 tickers (51.1%) → 120 in the frozen corpus.**

Rows are append-only and a retry appends beside its failure, so **read the last row per
`cik`**, not the first.

### `scores/*.json` — a persisted scoring pass

```json
{ "band": "clean", "split": "dev", "vintage": "2026-09-05", "scored_on": "2026-09-09",
  "n": 175, "unscored": { "SpotDriftError": 3 },
  "commit": "83370f6…", "forecast_digest": "1997f735…", "freeze_digest": "7cf4ae3d…",
  "freeze_version": "2.6.0",
  "summaries": { "crps": ["M.A.P. vs garch: …"], "log score": [...] },
  "items": [ … 175 objects … ] }
```

`summaries` are **rendered sentences, already written** — display them verbatim. They
carry their own hedging ("indistinguishable at n=175 … this is not evidence of no
difference") and rewording them will overstate the result.

`items[]` holds per-item `map_crps`, `map_log_score`, `map_brier`, `map_pit`,
`map_sigma`, `map_probability_up`, `realised_return`, and `baseline_*` maps keyed by
baseline name. `unscored` counts items that could not be scored, by reason.

---

## 3. `corpus_relation` — four values

Where a run stands to the pre-registered panel. **This is the field to branch on.**

| Value | n | Sentence for the UI |
|---|---|---|
| `ledger_item` | **701** | *In the pre-registered panel.* |
| `repeat_of_exhibit` | **74** | *A frozen exhibit, but not the panel's run for it.* |
| `outside_corpus` | **4** | *Not part of the frozen corpus.* |
| `unchecked` | 0 | *Not compared — this export has no frozen record or ledger.* |

**`ledger_item` does not mean "scored".** A ledger entry promises the artifacts exist.
Whether an item was scored depends on its split and on `map evaluate` having run, and no
per-item score is persisted for any holdout item. Call it *in the panel*, never *scored*.

The **74 `repeat_of_exhibit`** runs are 10% of the log — re-runs, post-band repeats and
ablation replays of documents the corpus froze. They read a real corpus exhibit and are
not the panel's run for it. Do not count them in anything describing the panel.

`document_source` is a **separate axis** and the key of the four run files: `corpus`,
`edgar`, `news`, `unknown`. It is what the writer recorded; `corpus_relation` is derived
at read time. All 779 runs today are `unknown` because they predate the field — which is
not a claim that they came from nowhere. **Never merge the four files and filter**: the
separation exists so an out-of-corpus run cannot end up one `sum()` from a panel figure.

---

## 4. `outcome_status` — four values

| Value | n | Sentence for the UI |
|---|---|---|
| `closed` | **777** | *Horizon elapsed — close retrieved from the `<snapshot>` snapshot.* |
| `window_open` | **2** | *Horizon has not elapsed yet.* |
| `absent_from_snapshot` | 0 | *The price snapshot holds no window covering this anchor.* |
| `not_requested` | 0 | *Outcomes were not retrieved for this export.* |

The last three are separate on purpose: a gap in the stored series and a fact about the
calendar are different things, and showing the first as the second invents an answer out
of a missing file. Do not collapse them into "no outcome".

**The outcome is a retrieval, not a stored result.** `snapshot` names the pinned vintage
it was read from; `retrieved_on` is the day of the read; `provider` comes from that
file's own metadata. A run's own price vintage ends at its anchor and structurally cannot
hold its outcome — the bar did not exist when the run was written. Show it as
*"close 311.30 on 2026-08-20, retrieved from the 2026-09-05 snapshot"*.

---

## 5. Absence — three different meanings

The export distinguishes these, and a UI should too.

**Not applicable** — the field does not apply to this record.
`ledger_item: null` when `corpus_relation` is not `ledger_item`; `outcome: null` when
`outcome_status` is not `closed`; `most_recent: null` when `count` is 0. Show nothing.

**Not computed / not supplied** — the question was never put.
`document_is_frozen_exhibit: null` and `corpus_relation: "unchecked"` mean no frozen
record or ledger reached the export. `outcome_status: "not_requested"` means no snapshot
was named. `name: null` in `universe.json` means the symbol index was not exported.
These are **not** negatives: show *"not checked"*, never *"no"*.

**Cannot be computed** — the answer does not exist and will not.
`scores.absent` for the holdout, below.

Ambiguous by design, and documented as such: `freeze_version: null` and `arm: null` mean
*either* "not applicable" *or* "written before the field existed". Do not resolve them —
use `corpus_relation` for the first and treat a null `arm` as "no arm recorded".

**`manifest.absent[]`** lists inputs that could not be read at export time, each with
`what`, `path` and a `reason` naming the consequence. Where the absence is about a long
list of things, the entry also carries `items` — an array, so a UI can render it however
it likes:

```json
{ "what": "prices", "path": "var/prices",
  "reason": "120 of 120 companies have no window in the 2026-09-05 snapshot",
  "items": ["AAPL", "ACGL", "ACHC", …] }
```

`reason` is always a whole sentence and never contains the list. Use these to drive empty
states.

---

## 6. `arm` — experimental runs

`arm: null` on every run today. When present (`"A"`, `"C"`, `"control"`, …) the run is an
**ablation arm, not a projection**. Arm A replays the corpus from cache and its forecasts
are byte-identical to the panel's apart from `run_id`; listing them as separate forecasts
would inflate the log by 355. Label them and exclude them from any count of forecasts.

---

## 7. The manifest, and what `--check` compares

```json
{ "export_version": "1.1.0", "exported_at": "2026-09-09",
  "freeze":  { "version": "2.6.0", "digest": "7cf4ae3d…" },
  "code":    { "commit": "8bc86c5…", "forecast_digest": null },
  "ledger":  { "items_settled": 709 },
  "symbols": { "synced_on": "2026-08-11" },
  "prices":  { "snapshot": "2026-09-05", "companies": 120 },
  "filers":  { "rows": 8001, "vintages": ["2026-09-09"] },
  "scores":  { "records": [ … ], "absent": [ … ] },
  "absent":  [ … ], "files": { … } }
```

| Field | Meaning |
|---|---|
| `export_version` | Shape of these files. Refuse a version you do not know. |
| `exported_at` | When the export ran. **A fact about the export, not about the data.** |
| `freeze.version` / `freeze.digest` | Which frozen corpus, and a hash of the fields that govern a forecast. |
| `code.commit` / `code.forecast_digest` | Which code. `forecast_digest: null` = built from an uncommitted tree. |
| `ledger.items_settled` | See below. |
| `symbols.synced_on` | Vintage of the symbol index — **a month older than the prices**, which is why there is no single export vintage. |
| `prices.snapshot` | The pinned price vintage every series and outcome was read from. |
| `filers.rows` / `filers.vintages` | Pre-screen size and the set of days it was walked over. |
| `files` | Every path written, with its byte size. |

Every stamp above is **carried from its own source**. The export mints only
`exported_at`, because one export-wide vintage would flatten several different moments
into one date and assert a uniformity that does not exist.

**`--check` re-derives seven identities from a live checkout and names what moved:**
`freeze.version`, `freeze.digest`, `code.commit`, `code.forecast_digest`,
`ledger.items_settled`, `symbols.synced_on`, `prices.snapshot`. It reports and refuses
nothing — whether a moved input matters depends on which one. A version mismatch is
reported first and in red, because comparing identities across two shapes compares fields
that may not mean the same thing.

---

## 8. Three things a consumer will get wrong

### `ledger.items_settled` is **not** a run count

It is **709** = 701 completed + 8 that failed terminally. It counts every corpus item the
ledger will not attempt again, which is exactly why 8 filings in `corpus.json` carry an
empty `runs` array.

Call it **"corpus items settled"**, or do not show it. If a UI needs "forecasts produced",
count `ledger_item` runs — **701** — or sum non-empty `runs` arrays. Labelling 709 as runs
overstates the corpus by 8.

### Two dev scoring records ship, and one describes a tree that no longer exists

```
scores/clean.dev.2026-09-05.1997f7352e47.json   forecast_digest: "1997f735…"   ← prefer
scores/clean.dev.2026-09-05.dirty.json          forecast_digest: null
```

Both are real passes over the same 175 items. **Tell them apart by `forecast_digest`**: a
null digest means the pass ran from an uncommitted tree, so nothing identifies the code
that produced it. **Prefer the record whose `forecast_digest` matches
`manifest.code.forecast_digest`**; failing that, prefer any non-null digest over `dirty`.

Do not show both as two results, and do not average them. This is one measurement
recorded twice under different code states — a scoring record is write-once per identity,
so a re-run under changed code lands beside its predecessor rather than replacing it.

### `scores.absent` for the holdout is a stated fact, not a missing file

```json
{ "split": "holdout", "exported": false,
  "reason": "The holdout was scored once. Its per-item scores were printed once and were
             never persisted, and they cannot be recovered…",
  "survives_in": "corpus/holdout_spend.jsonl (tracked; …)" }
```

The holdout was scored **once**, on 173 items, and `map evaluate --split holdout` is
refused before anything is computed once that spend is recorded. There is no re-run that
could produce these numbers.

**A UI must not imply the holdout is unscored, pending, or coming later.** It was spent,
the result is published, and the per-item detail is gone. Render this as *"scored once;
per-item detail not retained"* with the reason available, and never as an empty state, a
spinner, or a dash. Treating it as missing data suggests a gap where there is a deliberate
protection.

---

## 9. What a fresh clone gets

The repository ships the corpus and nothing computed. `var/` and `runs/` are untracked, so
a cloner has no ledger, no symbol index, no prices, no pre-screen and no scores.

`map export` **stops** with exit 5 and names the first missing input:

```
error: the corpus ledger is missing at var/corpus/ledger.jsonl
  Run `map corpus run`, or pass --allow-partial to export without it.
```

`map export --allow-partial` succeeds and writes **0.09 MB**:

| Written | Missing |
|---|---|
| `manifest.json` | `symbols.json` |
| `universe.json` (120, every `name` null) | `filers.json` |
| `corpus.json` (709 filings, every `runs` empty) | `prices/` |
| `runs/by_source/*.json` (all four empty) | `scores/` |

with five entries in `manifest.absent[]`:

```
ledger   runs cannot be related to corpus items; every corpus_relation reads
         'unchecked' and the per-company run lists are empty
symbols  search cannot resolve tickers outside the corpus
prices   120 of 120 companies have no window in the 2026-09-05 snapshot
         + items: all 120 tickers
filers   search can say whether a ticker exists but not whether its filer
         publishes Item 2.02 8-Ks
scores   no scoring pass has been recorded
```

**This is the state to design empty states against.** It is what every cloner sees, and
it exercises every absence path at once: a full corpus with no runs, a universe with no
names, four empty populations, no chart data and no scores. A UI that renders this
correctly — naming each absence rather than showing zeros — will render a partial export
correctly too.

`map export --check` against a directory with no export exits 5 and names the command to
run.
