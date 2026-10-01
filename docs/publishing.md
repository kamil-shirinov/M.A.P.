# Publishing a copy a reviewer can click

The repository is private and **a clone cannot regenerate the export**. `var/` holds the
ledger, the run artifacts and the scoring passes, and none of it is committed — so a
reviewer who clones sees the No-export panel and nothing else. `map export
--allow-partial` gets them 0.09 MB: the frozen corpus, five named absences, and no runs,
no scores and no prices.

`scripts/build_site.sh` assembles a directory that can be served anywhere. **It does not
deploy.** Publishing is a separate, deliberate act, and has its own script
(`scripts/publish_site.sh`, below) that has never been run against the real remote:
the plan is written here, the first deploy happens on the laptop.

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

## Hosting: GitHub Pages, from an orphan `gh-pages` branch

**Planned, not deployed.** [ADR 0041](../decisions/0041-github-pages-from-an-orphan-branch.md)
has the reasoning and the alternatives.

The shape: `main` holds the code and never the export. A second branch, `gh-pages`,
shares no history with it and holds **only the built site, as one parentless commit that
is replaced on every deploy.** Pages serves that branch's root. The site is built on the
laptop, because only the laptop has `var/`; a CI runner has no export to publish.

### Once, before the first deploy

1. **Merge this work to `main`.** The script refuses a commit that is not on `origin/main`,
   so the published copy always names a commit anyone can read.
2. **Decide whether a public page is what you want.** This is the decision the script cannot
   make for you, and two facts bear on it:
   - **A Pages site is public, whatever the repository's visibility.** (Pages from a private
     repository also needs a paid plan, and a private-Pages option exists only on Enterprise
     Cloud: check what your account has.) The repository being private protects the
     source, not the site.
   - **`gh-pages` is a branch of this repository.** "Main never carries the export" is
     true; the repository does. Anyone who can read it can read the branch, and if the
     repository is ever made public the branch goes with it.
   - Leaving prices out removes the bulk series, not the third-party content: the table
     above still applies in full.
3. **Settings → Pages → Build and deployment → Deploy from a branch → `gh-pages` / `/ (root)`.**
   The branch does not exist until the first deploy, so this is done after it. The script
   prints the URL it should serve at: `https://<owner>.github.io/<repo>/`.

### Each deploy, on the laptop

```bash
scripts/publish_site.sh --dry-run   # build, verify, assemble, show; push nothing
scripts/publish_site.sh             # the same, then asks for the word "publish"
```

`--yes` skips the question, for a deploy you have already looked at. There is no flag to
name another branch, and none to include prices.

What it does, and refuses:

| Step | Refuses when |
|---|---|
| Commit | `HEAD` is not an ancestor of `origin/main` |
| Build (`build_site.sh`) | `config/` or `src/mapf/` is dirty; either suite or the style probe fails |
| Verify | `assets/export/prices/` exists; the manifest says any company was priced; the manifest is missing; any top-level entry is not a page, `assets/` or `robots.txt`; any `.parquet`, `.jsonl` or `.env` file is anywhere in it |
| Verify (warning only) | a `/Users/…` or `/home/…` path appears in a published file |
| Assemble | git `user.name` / `user.email` are not set |
| Confirm | the reply is not exactly `publish` |
| Push | the branch moved since the script looked (`--force-with-lease` against the commit it saw) |

The check on the build is separate from the build's own reason to leave prices out: the
exporter writes the manifest's absence in its own words, and the publish script reads the
result rather than trusting that the builder did what it was asked.

Only `refs/heads/gh-pages` is ever pushed. The temporary repository holding the site is
removed on exit; your clone is never switched to `gh-pages`.

### What cannot be taken back

A force-push replaces the branch; it does not recall what was there. GitHub keeps
unreachable commits retrievable by their hash, and publishing again does not change that.
That is the reason the price check refuses rather than warns, and why the script asks. To
take the *page* down: Settings → Pages → Unpublish, and delete the `gh-pages` branch.
Anything already fetched, cached or archived stays that way, as `robots.txt` says for
indexing and for nothing else.

### Not chosen

- **A `docs/` folder on `main`.** Puts the export on `main`, which is what this is arranged to avoid.
- **A GitHub Actions deploy.** The runner would need the export, which is not committed.
- **Another host** (`netlify deploy --dir=site --prod`, `vercel deploy site --prod`,
  `rsync -av --delete site/ user@host:/var/www/map/`). All still work on `site/`, and
  none of them has the "replace, with no history" property for free. `build_site.sh` still prints them.

`site/robots.txt` disallows indexing. That is a request, not a control: anything served
is public and may be cached or archived whether or not it is indexed. Decide on that
basis, not on the `robots.txt`.

`site/` is gitignored. It is derived from the export, which is itself derived.
