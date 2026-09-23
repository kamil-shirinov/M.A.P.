# The runs screen — what the data actually looks like

For CD, designing the third screen. This is a profile of the real export, measured on
2026-09-17, not a summary from memory. Every number below came from the files the page
will read.

**The export this describes:** `export_version` 1.2.0, freeze 2.6.0, code `b0596c4`,
exported 2026-09-17, price vintage 2026-09-05, symbol index 2026-08-11. Re-measure after
a re-export; these counts grow with the corpus.

---

## 1. One file, and what it costs

| File | Size | Rows |
|---|---|---|
| `runs/by_source/unknown.json` | **649.2 KB** | **779** |
| `runs/by_source/corpus.json` | 2 bytes | 0 |
| `runs/by_source/edgar.json` | 2 bytes | 0 |
| `runs/by_source/news.json` | 2 bytes | 0 |

Boot currently reads `manifest.json` (1.9 KB) and `universe.json` (7.5 KB) and nothing
else. This screen is the one place the 649.2 KB file is worth opening — the front door
deliberately does not, and takes its run count from the manifest instead.

**The four files are never concatenated by the export, and the library has no accessor
that returns all four.** They are four populations, not one list split for convenience.
Today three are empty, which is a fact to render, not a case to hide.

---

## 2. The two-population warning, which is the trap on this screen

Three numbers sit close together and mean different things:

| Number | What it counts |
|---|---|
| **779** | runs in the journal — every run that happened, including repeats and runs outside the corpus |
| **709** | corpus items the ledger has settled — `ledger.items_settled`, 701 completed **plus 8 that failed terminally** |
| **701** | filings with a completed run |

The rows on this screen are **runs**, so the screen is 779. The 8 terminal failures are
not runs and cannot appear as rows: nothing ran. They are named in §6 and belong on the
page as a stated absence pointing at the company pages that hold them — the same
treatment the company page gives ATI's missing panel run.

`ledger.items_settled` must not appear on this screen as a total.

---

## 3. Distributions

**Relation to the corpus** — every run carries `corpus_relation`:

| Value | Runs | Meaning |
|---|---|---|
| `ledger_item` | 701 | read a filing the frozen corpus holds; carries `ledger_item` with its ticker, band and filing date |
| `repeat_of_exhibit` | 74 | read an exhibit already read by a ledger run — a second pass, not a second filing |
| `outside_corpus` | 4 | read a document the corpus does not hold |

The 74 repeats fall on 53 tickers: 43 tickers have 1, four have 2, three have 3, one has
4, two have 5. All 4 outside-corpus runs are AAPL, two on 2026-08-13 (5-session) and two
on 2026-08-11 (21-session).

**Outcome** — 777 `closed`, 2 `window_open`. Both open ones are the same two AAPL
21-session runs from 2026-08-11; their `outcome` is null rather than a zero.

**Horizon** — 777 runs at 5 sessions, 2 at 21.

**Freeze version** — which frozen corpus the run executed under: 2.6.0 ×359, 2.4.0 ×214,
2.3.0 ×135, 2.5.0 ×3, and **68 with none at all** (they predate the field). **Four**
versions plus an absence — an earlier draft of this profile said five, and the screen's
freeze filter is built from the data rather than from that list.

**Drift** — 9 runs carry `anchor_drift`, where the pinned snapshot disagrees with the
spot the run recorded: 7 SCCO (ratio ≈0.988142) and 2 AAPL (≈1.007509). The export carries
**the ratio and nothing else** — no event, no size, no name. "A 1.012 split" is not in these
files: it is 1 ÷ 0.988142, and a split is one of several corporate actions with that shape.
The screen shows the ratio measured and, beside it, 1 ÷ ratio marked derived, called a
corporate action.

**Band and split** — of the 701 ledger runs, 351 are `clean` and 350 `ambiguous`. By the
ticker's split, the 779 runs divide 398 dev / 381 holdout.

**Document source** — all 779 are `unknown`. Not a claim about where they came from:
the field was added after these runs were made.

**Arm** — null on all 779. The four-arm ablation's 786 runs are **not in this journal**
(they live outside the export), so a page that reads as "every forecast ever made" would
be wrong. One line of chrome should say so.

---

## 4. The shape a layout has to survive

**By month** — 20 groups spanning 2025-01 to 2026-08, from **3 runs to 97**:

```
2025-01  27   2025-07  42   2026-01  83
2025-02  51   2025-08  43   2026-02  97
2025-03   5   2025-09   5   2026-03  11
2025-04  30   2025-10  56   2026-04  59
2025-05  56   2025-11  28   2026-05  65
2025-06   3   2025-12   4   2026-06   6
              2026-07  72   2026-08  36
```

Median group 39. Earnings season is the shape: February and July/January are three
times December or June.

**By ticker** — 120 tickers, 4 to 16 runs each, median 6.

**By anchor date** — 176 distinct dates, 1 to 22 runs each, median 3. The busiest are
2026-01-30 (22), 2026-04-30 (18), 2026-02-04 (18).

**Widths** — tickers are at most 5 characters; the longest company name is 36 (DJT).
`run_id` is a 36-character UUID, and **the first 5 characters are already unique across
all 779** — 4 collide on five pairs. An abbreviation is safe from 5 up; the screens use 8
to match each other, not because 8 is needed.

---

## 5. What a row carries

```json
{ "run_id": "46cf0ac0-ef19-4769-8718-09f2df365f41", "ticker": "AAPL",
  "anchor_date": "2026-08-13", "anchor_spot": 302.9849853515625, "horizon_days": 5,
  "scenarios": [{ "name": "bullish", "probability_weight": 0.25,
                  "price_return": 0.012, "annualised_vol": 0.20 }, …],
  "document_source": "unknown", "freeze_version": null, "arm": null,
  "document_is_frozen_exhibit": false, "corpus_relation": "outside_corpus",
  "ledger_item": null,
  "outcome": { "trading_date": "2026-08-20", "close": 311.29998779296875,
               "provider": "yfinance", "adjustment": "split_adjusted",
               "snapshot": "2026-09-05", "retrieved_on": "2026-09-17" },
  "outcome_status": "closed" }
```

Every run has exactly 3 scenarios. `document_is_frozen_exhibit` is true on 775 of 779.

**`retrieved_on` moves on every export.** It is the day the export read the close: 2026-09-17
on all 777 closed runs today, 2026-09-09 a week ago. No copy may hardcode it — read it from
the row, as `describeOutcome` does.

Four things the fields do **not** support:

1. **No score per run.** Scoring records key their items on ticker and `as_of`, never
   `run_id`. There is no join, and the company page states this rather than implying a
   per-run number exists. A "score" column is not available at any price.
2. **`ledger_item` is present on 701 runs only** — null on repeats and outside-corpus
   runs. Its `filing_date` is carried from the ledger and must never be derived from
   `anchor_date`, in either direction: the anchor equals the filing date on 66 runs and
   filing + 1 on 635.
3. **`outcome` is null while a window is open.** Absent, not zero.
4. **`freeze_version` null means unrecorded**, not "no freeze".

---

## 6. The 8 filings with no run

Nothing ran on these, so they cannot be rows here. Each is on a company page, where the
filing shows with an empty run list:

| Ticker | Filed | Band | Split |
|---|---|---|---|
| ACGL | 2026-02-09 | clean | dev |
| ALLY | 2026-01-21 | clean | holdout |
| ATI | 2025-02-04 | ambiguous | holdout |
| ATI | 2026-02-03 | clean | holdout |
| JAZZ | 2026-08-03 | clean | dev |
| TROW | 2025-02-05 | ambiguous | dev |
| UHS | 2025-02-27 | ambiguous | dev |
| WH | 2026-04-29 | clean | holdout |

---

## 7. Rules this screen inherits from the two already built

- **Every digit on screen is either a marked figure or marked chrome.** An unmarked
  number outlines itself in the page and throws in the console on the next paint. Counts
  the page computes go through `figure()`; dates, ids, form numbers and quoted counts go
  through `chrome()` with the reason their digits are there.
- **Absence is stated, never blank.** Three kinds — not applicable, not computed, cannot
  be computed — and the page prints the reason the boundary gave.
- **Populations are not pooled silently.** Where a total across sources is genuinely
  wanted, the addition happens in page code where it can be seen, as the front door's
  strip does.
- **Provenance travels with the number**: measured (read from an artifact), derived
  (computed here), fabricated (from a fixture). Weakest input wins.
- Layout tokens exist and are shared: a wide frame (`--measure`) with prose capped
  inside it (`--measure-prose`), the masthead, the footer and section headers.

---

## 8. The design problems, stated plainly

1. **779 rows.** All at once is a wall; 20 month groups range from 3 to 97, so uniform
   grouping produces both a stub and a wall.
2. **Four filter axes** — ticker, relation, outcome, freeze version — and all filtering is
   client-side, because there is no server.
3. **Three empty populations** that must read as deliberate rather than broken.
4. **The 8 non-runs** must be reachable from this screen without becoming rows on it.
5. **The nav item is now "runs"**, not "run ledger": the rows are runs, and "ledger" is
   the corpus ledger's word.
