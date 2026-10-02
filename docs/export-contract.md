# The `map export` contract

What `map export --out <dir>` writes, field by field, for a front end reading it as
static assets. No server runs behind these files.

```bash
uv run map export --out ./export          # write it
uv run map export --out ./export --check  # has anything moved since?
```

`export_version` is **1.5.0**. It is the shape of these files, not the age of the data
— read it first and refuse a version you do not know. Every size below is at the
current corpus (120 companies, 709 filings, 779 runs, three scoring passes) and will
grow with it.

---

## 1. Files

| Path | Load | Size | Rows |
|---|---|---|---|
| `manifest.json` | **eager, first** | 2.2 KB | — |
| `universe.json` | **eager** | 7.5 KB | 120 |
| `corpus.json` | **eager** | 108.8 KB | 120 |
| `runs/by_source/corpus.json` | **eager** | 0.0 KB | 0 |
| `runs/by_source/edgar.json` | **eager** | 0.0 KB | 0 |
| `runs/by_source/news.json` | **eager** | 0.0 KB | 0 |
| `runs/by_source/unknown.json` | **eager** | 649.2 KB | 779 |
| `symbols.json` | lazy | 864.5 KB | 10,398 |
| `filers.json` | lazy | 1,234.4 KB | 8,001 |
| `prices/<TICKER>.json` | lazy, per company | 2,074.1 KB total · 17.3 KB median | 120 files |
| `scores/<band>.<split>.<vintage>.<digest>.json` | lazy | 133.5 KB each | 3 files |
| `scores/holdout_spend.json` | lazy | 0.4 KB | 1 spend |
| `live/replay.json` | lazy | 0.9 KB | 1 run |

**Eager total 0.77 MB. Whole export 5.34 MB.**

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
   "exchange": "Nasdaq",
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
  "anchor_date": "2026-08-13", "made_at": "2026-08-30T22:07:59.198329+00:00",
  "anchor_spot": 302.9849853515625, "horizon_days": 5,
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
| `made_at` | datetime (UTC) \| null | **When the run was made**: the first event in its own trace, stamped by the run's clock as it happened. Not `anchor_date` — a run made before a session settles opens from the previous close, so the two are different days — and not the forecast's `as_of`, which for a corpus run is a point-in-time instant months before the run happened. `null` when the run left no trace to read it from (63 run directories hold none and 23 an empty one); never filled from another field. A page shows it in the viewer's time zone. Added in 1.5.0. |
| `anchor_spot` | float | The close the forecast was produced against. Float32 from the provider, so display to 2dp; the stored value is exact. |
| `horizon_days` | int | Horizon in **trading** sessions, not calendar days. |
| `scenarios` | array of 3 | Always `bullish`, `base_case`, `bearish`, in that order. `probability_weight` sums to 1.0 (±1e-6). `price_return` and `annualised_vol` are **decimal fractions** — `0.012` is 1.2%, not 1.2. |
| `document_source` | see §3 | Where the document came from, **as the writer recorded it**. |
| `freeze_version` | string \| null | Which frozen record governed the run. null = outside a corpus, *or* predates the field. Ambiguous by design — use `corpus_relation`. |
| `arm` | string \| null | Experimental arm. See §6. |
| `document_is_frozen_exhibit` | bool \| null | Whether this run's document is an exhibit in `frozen.json`: by hash, or, for a run whose filing is known (recorded in manifest 1.10.0, or read off an older run's trace), by accession too. **null = not checked.** |
| `corpus_relation` | see §3 | Where the run stands to the pre-registered panel. **Use this, not the two fields above.** |
| `ledger_item` | object \| null | `{ticker, band, filing_date}` — present only when `corpus_relation` is `ledger_item`. |
| `price_kind` | `"close"` \| `"intraday"` \| `"unknown"` | Whether `anchor_spot` was a settled close or a quote taken while the session was still trading. Decided from what the run recorded: a `fetched_on` later than the price bar proves the bar had settled; a same-day fetch is judged from the run's own `as_of` against 16:30 New York. **Not from `as_of` alone** — corpus runs carry a synthetic `as_of` at 00:00 UTC on the bar's date, the evening before that session opened. Three runs are `intraday`. Added in 1.3.0. |
| `anchor_drift` | object \| null | Set when the snapshot's close at the anchor disagrees with `anchor_spot`, with a `cause`. See §4a. |
| `outcome` | object \| null | The realised close. Present only when `outcome_status` is `closed`. |
| `outcome_status` | see §4 | Why there is or is not an outcome. |

**Rows are sorted by `anchor_date`, newest first**, within each of the four files. Do
not re-sort to display most-recent-first; you already have it.

**`ledger_item.filing_date` is carried, never derivable — in either direction.** A corpus
forecast is dated the day *after* the filing it reads, and its anchor is the trading
session that resolves to. Only **66 of 701** have `filing_date == anchor_date`.

Both directions of that arithmetic are wrong, and the second does not read as covered by
a warning written about the first:

| you have | you want | why it fails |
|---|---|---|
| an anchor | the filing date | `anchor − 1` is wrong on the 66 where they coincide |
| a filing date | the anchor | `filed + 1` is wrong on the same 66, from the other side |

The second form is the one that bites, because it looks like a lookup rather than a
derivation. **A repeat's panel run is the ledger run at the same `anchor_date`** — that
resolves 73 of the 74 repeats unambiguously, and the 74th has no panel run at all. Never
find it by date, in either direction. Having found it, read `filing_date` off its
`ledger_item`.

Where no panel run exists there is nothing to carry the date, and a filing must be
matched by date. Match `anchor` **or** `anchor − 1`: across all 701 runs the anchor is
one of those two and never anything else, so the pair is exhaustive where either alone
is not.

**There is no reliable key joining a run to its scored item, and the obvious one is the
same trap.** A scored item carries `as_of` — the forecast's *own* date, the day after the
filing. A run carries `anchor_date` — the trading *session* it opened from. These
coincide only when the forecast date happens to be a trading day, so:

```
join on (ticker, as_of) == (ticker, anchor_date)
  → 161 of 175 scored items match a run
  → 14 do not: 13 Saturdays, plus Good Friday 2026-04-03
```

Right 92% of the time, which is worse than never working: a sample of a few rows agrees
and the gaps are invisible without a count.

The reverse direction has a second hazard. Of **701** `ledger_item` runs, only **161**
find a scored item by that key — not because the rest went unscored, but because the
exported record covers **clean/dev only, 175 items**. The ambiguous band and the entire
holdout are legitimately outside it. A UI that renders "no score found" as *"this run was
not scored"* will say it about 540 runs, most of which were.

**So do not stitch scores onto runs.** Show a scoring record whole — it is a band-and-split
result and reads as one — and show a run's forecast and outcome from the run. If the two
must be related, relate them at the level the data supports: band, split and vintage, all
of which both sides carry.

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

`bars` is `[date, close]` pairs, ascending, from the **most recent window the pinned
vintage holds** — median 526 bars, about two years. Closes only; there is no OHLC here.

Every run's `anchor_date` falls inside its company's series, so a run marker can always
be placed. (Selecting the *longest* window instead put 296 of 779 anchors off the end of
their own chart; see Findings #56.)

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

There are **no interval fields** — no `p10`, `p50` or `p90`. A band can be reconstructed
from `map_sigma`, but that is modelling, not reading, and the export does not do it for
you.

An item's `as_of` is the forecast's own date and **does not join to a run's
`anchor_date`** — see the run journal section above before reaching for that key.

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

**A live run is judged by the same rule the live page uses** (ADR 0043): its document's
hash first, then the accession of the filing it read, because a re-fetch of the same
filing can arrive as different bytes. A run's manifest records the accession from format
1.10.0; for an older run the journal reads it off the source URL in the run's own trace
(nothing is edited), and a run for which neither exists has only its hash to go on.

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

## 4a. `anchor_drift` — the snapshot disagrees with the run

```json
"anchor_drift": { "recorded_spot": 185.0, "snapshot_close": 182.806, "ratio": 0.988142,
                  "cause": "corporate_action" }
```

`null` on all but **9** runs, where the close at the anchor in the pinned snapshot is not
the price the forecast was produced from.

**`cause` says why, and there are two.** `corporate_action`: the run read a settled close,
and a later adjustment re-based the series — 7 SCCO, one factor, ≈0.988142.
`intraday_anchor`: the run read a bar whose session was still trading, so its price
never was a close — 2 AAPL, made at 13:02 and 13:11 New York time on 2026-08-13, one
factor (≈1.007509) because they read the same unfinished bar nine minutes apart.
`unknown` when the run did not record enough to tell. Added in 1.3.0; **before it,
every consumer inferred "corporate action" from the fact of a ratio**, and all nine
were labelled that way. The cause comes from the row's `price_kind`, never from the
size of the ratio.

**`ratio` is not a groupable key.** It is computed per run from that run's own recorded
spot, and both sides are float32 off the wire, so the nine rows carry **seven distinct
float values** for **two** events of two different kinds:

```
SCCO  0.9881423249262894   0.9881423325818092   0.9881423105034546
      0.9881422964658348   0.9881422790266337   0.9881422904830778
AAPL  1.007508703480546  (both rows)
```

Grouping on equality gives seven groups where there are two events. **Group on `ticker`
and `cause`, or round** — six decimal places collapses these nine rows to the two values
above. The app groups on ticker and cause, because a ticker could carry both kinds.
Display the same way: `×0.988142`, not the full float.

**Scoring refuses these items, whatever the cause.** A return whose endpoints come from two
different prices is wrong while every individual number stays plausible, so `SpotDriftError` fires and the
item is not scored. The three SCCO clean/dev items are exactly the `"unscored":
{"SpotDriftError": 3}` in the scoring record, and **SCCO appears nowhere among the 175
scored items**.

**But the outcome is still exported, and must be.** An outcome that exists and is not
comparable is a different fact from an outcome that does not exist, and the journal never
omits a row. The marker is what stops those two facts looking identical.

Sentence for the UI:

> *The price series has been re-based since this run — a corporate action applied
> afterwards. This outcome is not part of any published score.*

Do not show a drifted outcome beside undrifted ones without the marker, and do not put
one in any figure that aggregates outcomes.

**Named for the drift, not for "scoring declined it."** Of the 9, six are `ledger_item`,
one is `repeat_of_exhibit` and two are `outside_corpus` — the last three were never
attempted by any scoring pass, so "declined" would be false for them. The drift is a fact
about the price series; the consequence for scoring is a consequence.

`null` means the anchor agrees **or** that no window was available to compare.
`outcome_status` tells you which: the check is possible exactly when it reads `closed` or
`window_open`.

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
{ "export_version": "1.5.0", "exported_at": "2026-09-30",
  "freeze":  { "version": "2.6.0", "digest": "7cf4ae3d…" },
  "code":    { "commit": "e5a38f2…", "forecast_digest": "fb673274…" },
  "ledger":  { "items_settled": 709 },
  "runs":    { "rows": { "corpus": 0, "edgar": 0, "news": 0, "unknown": 779 } },
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
| `code.commit` / `code.forecast_digest` | Which code. The digest hashes only the files that can produce a forecast (`config/`, `src/mapf/`, minus scoring, rendering and evaluation), so it does **not** move when scoring or CLI-reporting code changes. `null` = the tree was dirty when the export ran, in **any** file — including documentation, which cannot affect a forecast. Treat null as "unidentifiable", not as "changed". |
| `ledger.items_settled` | See below. |
| `runs.rows` | One count per `runs/by_source/` file, counted from the rows written into it — the per-population count `map runs` prints. **Four counts and no total.** A total would be the export pooling what its files keep apart; a consumer that wants one adds them, in code where that is visible. Added in 1.2.0. **Compared by `--check` since 1.3.0**, one key per source: a live run must move `runs.edgar` and nothing else, and if it ever moves the ledger or a freeze digest then something has written into the corpus. |
| `symbols.synced_on` | Vintage of the symbol index — **a month older than the prices**, which is why there is no single export vintage. |
| `prices.snapshot` | The pinned price vintage every series and outcome was read from. |
| `filers.rows` / `filers.distinct` / `filers.vintages` | Pre-screen size and the set of days it was walked over. **Rows are not filers**: 8,001 rows carry 7,998 distinct CIKs, because three were re-screened after a failed request and appear twice. The last row for a CIK is the pre-screen's answer. `distinct` added in 1.2.0. |
| `funnel` | The search screen's counts, over ONE base — tickers — computed at export because counting them in a browser means a pass over `filers.json` at 1.2 MB on every page load. `tickers` is the base; `earnings_filer`, `no_earnings_filings` and `unscreened` partition it exactly; `frozen` and `readable_unread` partition `earnings_filer`. Every part is counted, never subtracted. Added in 1.2.0. |
| `replay` | `{run_id, exported_as}`: the ONE recorded live run a copy with no models behind it shows, pinned by id in `export.py`. Never "the newest run" — that would republish whatever happened locally, which is a live claim by another route. `exported_as` is null when the pinned run is not in `runs/`, and then no `live/` file is written. Added in 1.3.0. |
| `files` | Every path written, with its byte size. |

Every identity stamp above is **carried from its own source**. The counts —
`prices.companies`, `filers.rows`, `runs.rows` — are counted from what the export read or
wrote. The export mints only `exported_at`, because one export-wide vintage would flatten several different moments
into one date and assert a uniformity that does not exist.

**Commit IDs are carried as recorded, including those written before the history cleanup
of 2026-09-30.** The cleanup gave every commit a new ID, and the export does not translate:
`code.commit`, a scoring record's `commit` and the holdout spend's `commit` are what their
sources wrote. An ID from before the cleanup resolves through
[`commit-map.tsv`](commit-map.tsv), and the app shows the published ID with the recorded
one beside it ([ADR 0038](../decisions/0038-commit-ids-after-the-history-cleanup.md)).
`--check` compares `code.commit` as written, so an export made before the cleanup reports
it as moved, which it has: the checkout now names a different commit.

**`--check` re-derives seven identities from a live checkout and names what moved:**
`freeze.version`, `freeze.digest`, `code.commit`, `code.forecast_digest`,
`ledger.items_settled`, `symbols.synced_on`, `prices.snapshot`. It reports and refuses
nothing — whether a moved input matters depends on which one. A version mismatch is
reported first and in red, because comparing identities across two shapes compares fields
that may not mean the same thing.

---

## 8. Five things a consumer will get wrong

### `live/replay.json` — one recorded run, for a copy with no models

```json
{ "run_id": "b8748710-…", "ticker": "KO", "anchor_date": "2026-09-28",
  "anchor_spot": 87.332, "horizon_days": 5, "corpus_relation": "outside_corpus",
  "price_kind": "intraday", "price_taken_at": "2026-09-28T19:52:43+00:00",
  "band": [{ "level": 0.1, "price": 84.005 }, …], "scenarios": [ … ],
  "fan": { "levels": [0.05, 0.1, …, 0.95],
           "sessions": [{ "session": 0, "prices": [87.332, …] }, …] },
  "scenario_paths": [{ "name": "bullish", "weight": 0.25, "prices": [87.332, …] }, …],
  "history": [["2026-06-26", 84.61], …, ["2026-09-28", 87.332]],
  "history_vintage": "2026-09-28", "history_why": null }
```

A `JournalEntry` as `runs/by_source/edgar.json` writes it, plus the fields the replay
needs and a journal row does not.

**`price_kind` is `close`, `intraday` or `unknown`,** and it is the reason this
block exists rather than the page simply printing `anchor_date`. A price provider
returns a daily bar for the session in progress and keeps updating it, so a run
made before 16:00 in New York anchors on a quote that looks exactly like a close.
This run was made at 15:52 ET, eight minutes before the bell. `price_taken_at` is
the run's own recorded instant, and the two together are what let a page say what
the price actually was instead of repeating a claim the artifact never checked.
The run itself is not edited — it is a record of what happened.

**`band`** is quantiles of the predictive distribution at 10/25/75/90, as prices,
from the same `simulate()` the scorer uses with the run's own scenarios and the
same seed. It is exported rather than sampled in the browser so that one quantity
has one implementation; a page that samples its own is a second estimator with no
way to say which answer a score would be computed against.

**`fan`** is the same distribution at every session from the anchor (session 0, every
level at the spot) to the horizon, at nineteen levels from 5% to 95% — nine central
intervals, 10% to 90%. It comes from `simulate_paths`, whose last session is
`simulate()`'s sample unchanged, so at the horizon `fan` and `band` agree to the last
digit at the four levels they share. The sessions between are a Brownian bridge to
that sample. Added in 1.4.0.

**`scenario_paths`** is each scenario's expected price at every session,
`spot × (1 + r)^(t/h)` — the mean the scenario's GBM is built to have, ending on the
price the scenario states. Added in 1.4.0.

**`history`** is up to 63 `[date, close]` pairs ending on the anchor, read from the
price vintage the run itself stored (`history_vintage`, the run manifest's
`prices.fetched_on`) — never fetched, and never the export's older snapshot — so its
last point is the price the forecast opened from. For this run that last point is the
intraday quote, as `price_kind` says. **null** with `history_why` stating the reason
when prices were left out (`--no-prices`) or that vintage holds no window. Added in
1.4.0.

### `ledger.items_settled` is **not** a run count

It is **709** = 701 completed + 8 that failed terminally. It counts every corpus item the
ledger will not attempt again, which is exactly why 8 filings in `corpus.json` carry an
empty `runs` array.

Call it **"corpus items settled"**, or do not show it. If a UI needs "forecasts produced",
count `ledger_item` runs — **701** — or sum non-empty `runs` arrays. Labelling 709 as runs
overstates the corpus by 8. And `runs.rows` sums to **779**, which is every run recorded —
repeats and the four outside the corpus included — not forecasts of corpus items.

### Two dev scoring records ship, and one describes a tree that no longer exists

```
scores/clean.dev.2026-09-05.1997f7352e47.json   forecast_digest: "1997f735…"   ← prefer
scores/clean.dev.2026-09-05.dirty.json          forecast_digest: null
```

Both are real passes over the same 175 items, and they differ only in whether the code
that ran them can be identified.

**The rule is: prefer a record with a non-null `forecast_digest`.** A null digest means
the pass ran from an uncommitted tree, so nothing names the code that produced it — the
filename says `dirty` for the same reason.

**Do not make matching `manifest.code.forecast_digest` the test.** That digest describes
the checkout the *export* ran from, and a scoring pass is almost always older than the
export that ships it — today the records read `1997f735…` and `null` against a manifest
digest of `fb673274…`, so neither matches and a UI keying on equality would reject both.
Equality means only "the export and this pass ran at the same code state", which is a
nice-to-have signal and not a selector.

Do not show both as two results, and do not average them. This is one measurement
recorded twice under different code states — a scoring record is write-once per identity,
so a re-run under changed code lands beside its predecessor rather than replacing it.

### `scores.absent` for the holdout is a stated fact, not a missing file

```json
{ "split": "holdout", "exported": false,
  "reason": "The holdout was scored once. Its per-item scores were printed once and were
             never persisted, and they cannot be recovered…",
  "survives_in": "corpus/holdout_spend.jsonl (tracked; its git history is the record of
                  the single spend)",
  "what_survives": [
    "the calibration coefficients and their fitted form",
    "the band, item count, date, commit, freeze version and price vintage" ],
  "exported_as": "scores/holdout_spend.json", "spends": 1 }
```

**`exported_as` names the file those terms are now in** — `scores/holdout_spend.json`,
the tracked `corpus/holdout_spend.jsonl` copied verbatim as a list, because the file is
append-only and a second spend would be a second line. It carries the coefficients
(`a`, `b`, the fitted form and what it was fitted on), the item count, the dates and the
identity stamps. **It carries no scores and cannot**: those were printed once and never
written. `exported` stays `false` for exactly that reason — the terms travel, the
measurements do not — and `exported_as` is `null` when the spend record itself could not
be read, with the gap named in the manifest's own `absent` list.

**`what_survives` is the field to render from**, not `reason`. `reason` explains why the
per-item detail is gone and reads as an apology; `what_survives` says what a reader can
still go and look at, and is already a list a UI can lay out. Use `reason` as the
explanation behind it — a tooltip, a disclosure — and `survives_in` as the pointer.

The holdout was scored **once**, on 173 items, and `map evaluate --split holdout` is
refused before anything is computed once that spend is recorded. There is no re-run that
could produce these numbers.

**A UI must not imply the holdout is unscored, pending, or coming later.** It was spent,
the result is published, and the per-item detail is gone. Render this as *"scored once;
per-item detail not retained"* with the reason available, and never as an empty state, a
spinner, or a dash. Treating it as missing data suggests a gap where there is a deliberate
protection.

---

**Export from a clean tree.** `code.forecast_digest` is suppressed whenever `git status`
is non-empty in *any* file, documentation included, so an export taken mid-edit ships an
identity that says nothing — and the record-selection rule in §8 has nothing to work
against. Commit first. (Findings #54.)

---

### A scenario return and a realised return are not the same quantity

**`scenarios[].price_return` is a simple return. `items[].realised_return` is a log
return.** The simulation converts with `math.log1p(price_return)`; the scorer computes
`log(close / open)`.

One `asPercent()` helper applied to both is wrong, and **wrong in the shape that survives
a spot-check**: the two agree on small moves and separate on large ones, so checking a few
typical values passes and the error shows up on exactly the runs a reader will look at
hardest.

Displayed to one decimal place, how often the two conventions differ:

| Log return | Displays differently |
|---|---|
| 0–1% | 1.8% of values |
| 1–2% | 11.4% |
| 2–3% | 31.1% |
| 3–4% | 63.3% |
| 4–5% | 96.0% |
| above 4.4% | **every value** |

A log return of 0.021 reads `2.1%` under either helper. At 0.080 it is `8.0%` against
`8.3%`; at −0.082, `−8.2%` against `−7.9%`. The largest log return on which they still
agree is 0.04353.

So the failure is not a uniform small bias. It is **invisible where most scenario returns
sit and certain above 4.4%** — one-directional, and a plausible-looking return at every
magnitude.

| Quantity | Convention | To a price | To compare |
|---|---|---|---|
| `scenarios[].price_return` | simple | `anchor_spot × (1 + r)` | `log1p(r)` |
| `items[].realised_return` | log | `anchor_spot × exp(r)` | `expm1(r)` |

`annualised_vol` is also a decimal fraction — `0.22` is 22% annualised, not 0.22%.

**Do not compare a scenario's return to a realised return without converting one.** If a
UI wants "was the base case close to what happened", convert the realised log return with
`expm1` and compare to `price_return`, or convert both to prices off `anchor_spot`.

### 78 runs are reachable from no company page

`corpus.json`'s `filings[].runs` lists **only ledger runs — 701**. The 74
`repeat_of_exhibit` and 4 `outside_corpus` runs exist in `runs/by_source/` and are linked
from nothing.

This is correct: a filing's `runs` array answers *"which run is the panel's run for this
item"*, and a repeat is not. But a UI that builds company pages solely from `corpus.json`
will never surface those 78, and a user who reaches one from a global run list will find
no company page linking back to it.

If you want every run for a company, filter `runs/by_source/*.json` on `ticker` — and
show `corpus_relation` beside each, so a repeat is not mistaken for a panel item.

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
