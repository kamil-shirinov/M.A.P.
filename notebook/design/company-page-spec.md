<!-- Converted from RTF (TextEdit) to Markdown on 2026-09-30. The text is unchanged,
     including the footer's "export 1.1.0", which is kept as history: the export is 1.4.0 now. -->

# Company page — design handoff spec

## What the page is

A record of forecasts already made, for one company. Not a live forecast — the export holds none. No cone, no current projection, no per-run score.

## Which company to design against

The **common case is the default view**: six ledger runs, both bands, everything closed, no drift. 65 of 120 companies. This is what a reviewer opens.

The distinctive states live on one or two companies each and must not drive the layout:

- `outside_corpus` run — 1 company (AAPL); 4 runs corpus-wide
- `window_open` — 1 company (AAPL); the same two AAPL rows, horizon 21
- `anchor_drift` — 2 companies (AAPL ~1.007509, SCCO ~0.988142); 9 runs
- filing with `runs: []` — 8 filings corpus-wide; ATI 2026-02-03 is the interesting one

Every open-window run is also an outside-corpus run. They are the same two rows.

The artifact ships three example datasets behind an `example` prop — `typical` (default), `ati`, `aapl` — so each state can be seen without pretending it is common.

## Horizons

Only two exist across all 779 runs: **5 and 21**. 21 appears solely on the two AAPL outside-corpus rows. No horizon selector, no horizon axis, nothing implying a range.

## Runs: cards, no table

Max runs for any company is 16, median 6, min 4. The eighteen-run collapse threshold never fires — **the table branch is deleted**. Cards only on this screen. The run ledger is a different screen with different volume and needs its own table.

## Sections, top to bottom

1. **Masthead** — M.A.P., "Market's Agentic Projections — local inference, scored forecasts"; right-aligned vintage line (prices, symbols).
2. **Identity** — ticker (mono, 1.75rem), split badge, name (`null` renders "name not exported"), CIK (filer id, not a quantity), Exchange = *not loaded*, corpus counts. Standing paragraph: this is a record, not a projection; N of M horizons for **this company** have closed; corpus-wide 777 of 779, explicitly marked as a corpus total. Second paragraph: exchange sits in `symbols.json`, loaded lazily on the first search keystroke — absent rather than unknown; the page does not fetch a megabyte to fill one field.
3. **Price series and when runs opened** — closes only, snapshot vintage in the header, "last close on `<date>`" never "current". Legend: close line, run anchor, outcome close, re-based anchor (only when present), open window (only when present). No y-axis ticks — the export gives closes and an invented tick is a figure without provenance.
4. **Filings the corpus holds** — every filing, including ones settled without a run. Columns: Filed / Band / Accession / Panel run.
5. **Runs for this company** — cards, newest first, never re-sorted. Each card: anchor date, anchor close, horizon, `corpus_relation` badge + why, three scenarios, outcome sentence, conditional drift block.
6. **Scoring** — related at band, split and vintage only; never per item. Two refusals.
7. **Footer** — four independent vintage stamps (export 1.1.0, prices 2026-09-05, symbols 2026-08-11, freeze 2.6.0) and the line that there is no single export vintage.

## The three panel-run states

A `repeat_of_exhibit` run gets one of:

1. **Linked, marked inferred.** Panel run exists. Copy: read the exhibit filed `<date>`; a panel run anchored `<date>`; the pairing is matched on `(ticker, anchor_date)`, not a key — `source_doc_ids` is not exported, so nothing in the data states the two runs read the same document; unambiguous for 73 of 74 repeats, and still inference; the panel's run is the pre-registered one, this is not, and it is counted in nothing that describes the panel. Visual: dashed-underline link plus an "inferred link" tag. One direction only — panel runs do not link back.
2. **Panel run does not exist.** ATI: clean filing 2026-02-03 has `runs: []` (terminal failure) while a `repeat_of_exhibit` run sits at anchor 2026-02-04 having read that exhibit. No link, because there is nothing to link to. Amber left rule. Copy explicitly distinguishes it from "exists but not shown here".
3. **Not a repeat** — no block at all.

The filings table mirrors state 2: the row reads "held, not run" with a sub-note that a repeat read the exhibit. Cross-link stays one-directional.

## Band column

`clean` = after the training cutoff; `ambiguous` = before it, measures leakage. Both neutral — amber is reserved for uncalibrated and for the missing-panel-run rule. Accession `null` renders "predates accession storage", never blank.

## Outcome states — four sentences, never collapsed

- `closed` 777 — horizon elapsed; close retrieved from the pinned snapshot, with the provider and adjustment it names.
- `window_open` 2 — horizon has not elapsed yet. Both are outside-corpus runs at horizon 21.
- `absent_from_snapshot` 0 — the price snapshot holds no window covering this anchor.
- `not_requested` 0 — outcomes were not retrieved for this export.

A gap in the stored series, a fact about the calendar, and an outcome never requested are three different things.

## Drift block

Shown only when `anchor_drift` is non-null. Displays ×0.988142 at 6dp (`ratio3` is not a substitute). Body: the price series carries a corporate action applied after the forecast was written, so the anchor in the snapshot is not the price this run was produced from. Tail differs by outcome status — closed: not part of any published score, kept out of every figure that aggregates outcomes; open: nothing to exclude yet, and when the window closes it stays out.

## Scoring section

Lead: no score is attached to a run on this page, and none can be. A run carries its own forecast and outcome; a scoring record is a separate pass over a band and a split. Related at `band`, `split`, `vintage` — never per item.

- **dev**: one pass, 175 items corpus-wide, 161 matched to runs, 3 unscored (SpotDriftError), scored 2026-09-09, code 1997f735 identified. A second record for the same items ships from an unidentifiable tree — same measurement recorded twice under different code states, not two results; the identified one shows and the other is not averaged in. Summaries display verbatim.
- **holdout**: scored once on 173 items; spend recorded; further evaluation refused before anything is computed. What survives: the calibration coefficients and their fitted form; the band, item count, date, commit, freeze version and price vintage. Recorded in `corpus/holdout_spend.jsonl`. Not an empty state — nothing is coming later.

## Two renderings the page refuses

- **"Not scored."** The record covers one band and one split. Most panel runs sit outside its scope legitimately — the ambiguous band and the whole holdout were never in scope. Printing the negative would falsely claim scored-eligible runs went unscored.
- **A reconstructed band.** Scored items carry `map_sigma` but no p10/p50/p90. Building a band from sigma is modelling presented as reading. The percentiles do not exist, so the column does not either.

## Formatting conventions

Two return conventions, never converted into each other on this page:

- scenario `price_return` / `annualised_vol` are simple decimal fractions → `fmt.pct` / `fmt.pctSigned`
- `items[].realised_return` is a log return → `fmt.logpct` (expm1 first); missing from format.js today, added by patch 0002
- `anchor_drift` → `fmt.ratio` at 6dp (patch 0002; `ratio3` truncates to 0.988)
- prices at 2dp, `toLocaleString("en-US")` with min/max 2 fraction digits
- weights rounded to whole percent

## Tokens

```
paper    #0a0c10    surface  #12151c    sunken   #171b23
ink      #e4e8ef    ink-num  #f6f8fc    ink-2    #98a1b0    ink-3 #69717f
rule     #1c212a    rule-2   #29303c
accent   #4d8df0    accent-soft #12243f
up       #46a06b    down     #cf6a63
uncal    #d9a14a    uncal-soft  #2a2011
radius 2px   shadow 0 0 0 1px rgba(0,0,0,.35)
```

Type: Inter 400/500/600, JetBrains Mono 400/500/600. Steps: 0.6875 / 0.78125 / 0.875 / 1 / 1.3125 / 1.75rem. Spacing: 0.125 / 0.25 / 0.5 / 0.75 / 1.125 / 1.625 / 2.25rem. All numerals mono with `font-variant-numeric: tabular-nums`. Section headers are 0.6875rem uppercase, `letter-spacing: .12em`, `--ink-2`. Amber is reserved for uncalibrated and the missing-panel-run rule; red (`down`) for drift and refusals; accent for panel membership.

## Data bindings

- identity, split → universe.json {ticker, name, split}
- filings, bands, accession, `runs[]` → `corpus.json` (709 filings / 120 companies; 8 with empty `runs[]`)
- run cards → `runs/by_source/*` — 4 files, never merge-and-filter; sorted by `anchor_date` newest first, do not re-sort
- `filing_date` on a card → `ledger_item.filing_date`, read never derived (only 66/701 equal `anchor_date`)
- chart, last close, snapshot → `prices/<T>.json`, bars ascending `[date, close]`; show the `snapshot` vintage adjacent
- exchange → `symbols.json`, not loaded on this page
- scoring → `scores/*.json`, summaries verbatim
- relation branch → `corpus_relation`: `ledger_item` 701 / `repeat_of_exhibit` 74 / `outside_corpus` 4 / `unchecked` 0. `ledger_item` ≠ scored. Exclude repeats from panel figures.
