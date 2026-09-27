# Publishing a copy a reviewer can click

The repository is private and **a clone cannot regenerate the export**. `var/` holds the
ledger, the run artifacts and the scoring passes, and none of it is committed — so a
reviewer who clones sees the No-export panel and nothing else. `map export
--allow-partial` gets them 0.09 MB: the frozen corpus, five named absences, and no runs,
no scores and no prices.

`scripts/build_site.sh` assembles a directory that can be served anywhere. **It does not
deploy.** Publishing is a separate, deliberate act.

```bash
scripts/build_site.sh                 # -> site/, 3.7 MB, without the price series
scripts/build_site.sh --with-prices   # -> site/, 6.0 MB, the whole export
python3 -m http.server -d site 8000   # look at it before deciding anything
```

The script refuses to build from a tree with uncommitted changes under `config/` or
`src/mapf/`, because such an export records `forecast_digest: null` and the published
copy could not be tied to any commit. It runs both suites and the style probe first.

## What `--no-prices` leaves out, and what it does not

`prices/*.json` is **62,990 daily closes across 120 companies**, 2024-07-31 to
2026-09-03, from yfinance. It is 2.3 MB of a 5.5 MB export — 47% of the payload — and it
feeds exactly one thing: the price chart on the company page. Without it that section
states the absence it already knows how to state, in the export's own words, and every
other figure on every screen is unchanged.

**It is not all the third-party data, and removing it does not make the copy
first-party.** Every file below still carries data obtained from someone else:

| File | Third-party content | Source |
|---|---|---|
| `runs/by_source/unknown.json` | **1,556 market values** — 779 `anchor_spot` and 777 `outcome.close`, touching 1,403 distinct (ticker, date) pairs; plus 9 `anchor_drift.snapshot_close` | yfinance, split-adjusted |
| `scores/*.json` | **524 `realised_return`** values (175 + 175 + 174), each computed from two of those closes | yfinance, via the runs |
| `symbols.json` | 10,398 ticker / name / exchange / CIK rows | SEC `company_tickers_exchange.json` |
| `filers.json` | 8,001 filer rows — Item 2.02 pre-screen results | SEC EDGAR |
| `corpus.json` | 709 accession numbers and filing dates | SEC EDGAR |
| `universe.json` | 120 company names | SEC symbol index |
| `prices/*.json` | 62,990 daily closes | yfinance — **this is what `--no-prices` omits** |

Only `scores/holdout_spend.json` and the `map_*` / `baseline_*` score columns are
entirely M.A.P.'s own.

So the trade `--no-prices` actually makes is: **drop the bulk time series, keep the
1,556 individual closes the journal needs to show what each run opened from and closed
at.** Those are not removable without removing the journal, which is most of the app.
What it buys is the removal of a redistributable *dataset* — a 120-file daily series
somebody could take and use — while keeping the individual figures that are evidence for
particular claims.

## When you deploy

The build prints the three commands and runs none of them:

```
# netlify deploy --dir=site --prod
# vercel deploy site --prod
# rsync -av --delete site/ user@host:/var/www/map/
```

`site/robots.txt` disallows indexing. That is a request, not a control: anything served
is public and may be cached or archived whether or not it is indexed. Decide on that
basis, not on the `robots.txt`.

`site/` is gitignored. It is derived from the export, which is itself derived.
