# CLI reference

`map run`, `map prices`, `map runs`, `map export`. Exit codes are shared across
every command: `0` success, `2` bad arguments, `3` configuration, `4` inference,
`5` data, `6` unusable model output.

---

## CLI reference — `map run`

One forecast, end to end: prices, three agents in sequence, a Monte Carlo fan, and
four artifacts under `runs/<run_id>/` (`forecast.json`, `manifest.json`,
`trace.jsonl`, `chart.html`).

```bash
uv run map run AAPL                          # from the configured news directory
uv run map run AAPL --from-edgar             # from the filer's latest Item 2.02 8-K
uv run map run AAPL --horizon 21 --news-dir ./inbox
```

| Flag | Default | What it does |
|---|---|---|
| `TICKER` | *required* | The symbol to forecast, e.g. `AAPL`. |
| `--horizon` | `5` | Horizon in **trading** days, 1–252 (ADR 0016). |
| `--news-dir` | `news.dir` | Read documents from this directory instead of the configured one. |
| `--from-edgar` | off | Fetch the document from EDGAR instead. See below. |
| `--edgar-days` | `120` | How far back `--from-edgar` searches. Minimum 1. |
| `--fixtures` | — | Replay recorded LLM exchanges; no server needed. |
| `--record-to` | — | Record this run's LLM exchanges as replayable fixtures. Destination is mandatory. |
| `--config` | `config/default.toml` | Config file to load instead of the default. |

Exit codes are shared across every command: `0` success, `2` bad arguments, `3`
configuration, `4` inference, `5` data, `6` unusable model output.

### `--from-edgar`

Discovers the filer's most recent 8-K Item 2.02 within `--edgar-days`, takes the
newest, fetches the earnings exhibit and cuts it to the intake budget with the same
`head_tail_v1` rule the corpus uses (ADR 0020) — so this path and the corpus path see
an identical document where the exhibit is identical.

**It is not a corpus run.** The filing is discovered at runtime and is not in
`corpus/frozen.json`, so the forecast is unscored, carries no band, and belongs in no
calibration figure. The manifest says so positively: `document_source` is `"edgar"`
here, `"news"` for the default path, and `"corpus"` for `map corpus run` (ADR 0034).
Do not pool them.

**It never falls back to news.** A ticker with no Item 2.02 in the window exits `5`
and names the interval it searched:

```
no 8-K Item 2.02 filing for AAPL between 2026-05-11 and 2026-09-08
```

— because "there is no filing" and "you searched the wrong ninety days" have opposite
remedies, and a silent fallback would forecast from unrelated commentary under a flag
asserting it came from a filing. `--from-edgar` with `--news-dir` is refused outright
(exit `2`) rather than resolved by precedence, for the same reason.

It needs a symbol index (`uv run map symbols sync`) to resolve the ticker to a CIK,
and a descriptive `data.sec.user_agent` — EDGAR returns `403` without one.

## CLI reference — `map prices`

A daily price series for one ticker, on demand. No inference, no artifacts, nothing
written — a company page needs a chart before any forecast exists.

```bash
uv run map prices AAPL --days 180        # a table
uv run map prices AAPL --days 90 --json  # for a front end
```

| Flag | Default | What it does |
|---|---|---|
| `TICKER` | *required* | The symbol to fetch. |
| `--days` | `180` | Calendar days of history to request. Minimum 1. |
| `--json` | off | Emit JSON instead of a table. |
| `--config` | `config/default.toml` | Config file to load instead of the default. |

**There is no "current price" in the output, and there cannot be.** Both providers
serve *daily bars*, so the most recent value is a close on a trading date — three
days old on a Monday morning. The JSON pairs them in one object for that reason:

```json
"last_close": { "close": 316.22, "trading_date": "2026-09-08" }
```

A consumer cannot destructure the value without also receiving the date it belongs
to. The table says `last close … on <date>` for the same reason.

## CLI reference — `map runs`

The run journal: every run under `runs/` with its anchor, what was forecast from it,
and — where the horizon has elapsed — the close it landed on.

```bash
uv run map runs --limit 10                 # ten most recent, outcomes fetched
uv run map runs --snapshot ""              # list forecasts, retrieve no outcomes
uv run map runs --source edgar --json      # one population, machine-readable
```

| Flag | Default | What it does |
|---|---|---|
| `--runs-dir` | `runs` | Where run artifacts live. |
| `--source` | all | One population only: `corpus`, `edgar`, `news`, `unknown`. |
| `--limit` | `20` | Most recent N by anchor date. `0` for all of them. |
| `--snapshot` | `2026-09-05` | Stored vintage outcomes are read from. Empty string retrieves none. |
| `--json` | off | Emit JSON instead of a listing. |
| `--config` | `config/default.toml` | Config file to load instead of the default. |

**Nothing here is a score** (ADR 0035). It logs what was forecast and what happened,
per item — no accuracy, no rolling CRPS, no hit rate, not even a realised return.
`runs/` is whatever has been run, a population defined after the fact by curiosity
and retries; a number over it would be real arithmetic on an unreal sample. Scores
come from `map evaluate` over the pre-registered panel in `corpus/frozen.json`,
against a pinned vintage, with the holdout spendable once (ADR 0031).

**Populations are never pooled.** Output is grouped by the manifest's
`document_source` — `corpus`, `edgar`, `news`, `unknown` — in both the listing and
the JSON, with per-section counts and no total. A `--from-edgar` run is outside
`frozen.json` and stays outside every scored set (ADR 0034). Runs written before that
field existed report as `unknown`, which is not a claim either way.

**Outcomes are retrieved, never stored.** Where a run's horizon has elapsed, the
close is read from the pinned scoring vintage and shown with the snapshot it came
from, the provider taken from that file's own metadata, and the date it was read:

```
outcome    close 311.30 on 2026-08-20 (yfinance)
           retrieved 2026-09-09 from the 2026-09-05 snapshot
```

Not the vintage the run itself was produced under — a run's own snapshot ends at its
anchor and structurally cannot hold the outcome, because that bar did not exist when
the snapshot was taken. Reading a pinned vintage is also what makes the number
reproducible; a live fetch would give a different close on a different day.

Every run gets one of four answers, per run and never by omission: `closed`,
`window_open` (the horizon has not elapsed), `absent_from_snapshot` (the vintage
holds no window covering that anchor), or `not_requested`. The last three are
separate on purpose — a gap in the stored series and a fact about the calendar are
different things, and reporting the first as the second invents an answer out of a
missing file. Over the 779 readable runs today: 777 closed, 2 still open.

The listing also reports directories it could not read — 47 of the 826 present today
are pre-manifest captures or a schema 1.0.0 forecast — rather than dropping them
quietly and looking like a complete history of a smaller number.

## CLI reference — `map export`

The readable state as flat JSON, for a front end with no server behind it.

```bash
uv run map export                  # write it to ui/assets/export
uv run map export --check          # has anything moved since?
uv run map export --out ./export   # somewhere else, for a diff
```

| Flag | Default | What it does |
|---|---|---|
| `--out` | `ui/assets/export` | Directory to write into. The default is where the front end reads. |
| `--no-prices` | off | Omit the per-company price series. The journal's own anchor and outcome closes stay; only the daily bars behind the company chart are left out. See `docs/publishing.md`. |
| `--check` | off | Compare an existing export against this checkout. Writes nothing. |
| `--snapshot` | `2026-09-05` | Price vintage the series and outcomes are read from. |
| `--frozen` · `--ledger-path` · `--runs-dir` · `--scores-dir` | repo paths | The inputs. |
| `--allow-partial` | off | Write what can be read, recording every absence in the manifest. |

```
manifest.json    identity of every input — read this first
universe.json    the 120 companies that have something to show      eager
corpus.json      all 709 held filings, each with the runs that read it
runs/by_source/{corpus,edgar,news,unknown}.json
symbols.json     the full 10,398-row index                          lazy
filers.json      the Item 2.02 pre-screen, 8,001 filer rows          lazy
prices/<TICKER>.json                                                lazy
scores/<band>.<split>.<vintage>.<digest>.json                       lazy
```

**5.34 MB total, 0.77 MB of it eager.** Only symbols, filers, prices and scores are lazy.

**Populations cannot be pooled.** There is no combined runs file — the four files
mirror `Journal`'s four accessors, so a consumer that wants everything concatenates
on purpose (ADR 0035). Records come from the same serialiser `map runs --json` uses.

**Every absence is stated, never a missing file.** An input that could not be read is
named in the manifest with its consequence. Missing inputs stop the export unless
`--allow-partial` is passed; the frozen corpus stops it either way. This includes the
holdout: `scores.absent` says the holdout was scored once, that its per-item scores
were never persisted and cannot be recovered, and what survives instead — so a reader
learns why there is no holdout record rather than inferring it from a gap.

**Staleness is checkable, not just dated.** The manifest records the identity of all
seven inputs — freeze version and digest, commit and forecast digest, ledger size,
symbol-index vintage, price snapshot. `--check` re-derives them and names what moved:

```
same       freeze.digest: 7cf4ae3de9a2e56b…
moved      ledger.resolved: 701 -> 709
check      1 of 7 inputs have moved
```

It reports rather than refuses. Whether a moved input matters depends on which one,
and only the reader knows that.

## CLI reference — `map serve`

The app, and the endpoints behind it, on one loopback origin (ADR 0036). Every
company page ends with **Live runs, outside the record**; with a server behind the
page, Analyse there starts a run and the page shows its progress and its fan.

```bash
uv run map serve                                         # 127.0.0.1:8765, opens search
uv run map serve --replay <run_id> --replay-speed 20     # watch a recorded run; runs nothing
```

| Flag | Default | What it does |
|---|---|---|
| `--port` | `8765` | Loopback port for the app and the endpoints. |
| `--ui-dir` | `ui` | The app directory to serve. |
| `--edgar-days` | `120` | How far back to look for the latest Item 2.02. |
| `--fixtures` | off | Replay recorded LLM exchanges instead of calling a model server. A live prompt carries today's filing, date and spot, so a fixture only matches the exact request it was recorded from. |
| `--runs-dir` | `runs` | Where runs are written, and where a company page's live runs are read from. Point it at a temporary directory for screenshots (Findings #63). |
| `--replay` | off | Development aid. Analyse is answered by a recorded run: its own trace, each stage at the gap it recorded, then the result the export gives that run. Only for that run's company and horizon. Runs nothing, writes nothing, and says so in the terminal and on the page. |
| `--replay-speed` | `1` | With `--replay`: how many times faster than recorded, up to 60. |
| `--frozen` · `--spend-path` | repo paths | The freeze (for the relation tag) and the fitted correction. |
| `--open/--no-open` | open | Open search in a browser on start. |

Any flag that stops the server making or recording a real run puts **NOT A REAL
ANALYSIS SERVER** at the top of its output.

| Route | What it answers |
|---|---|
| `GET /health` | Whether a server is behind the page. Asked once per page. |
| `GET /prices?ticker=` | The company's closes over exactly the last two years to New York's today, split-adjusted like the pinned snapshot, through this machine's price cache, with the window and the day they were fetched; the unfinished session is dropped. The company page draws them in place of the snapshot, with the snapshot beside them (ADR 0039). |
| `GET /quote?ticker=` | The latest trade from Yahoo Finance, the time it traded, whether the market is open — New York's clock inside regular hours **and** a trade dated today — and when to ask again: about a minute while open, the next opening bell while shut. For the page only; no run reads it (ADR 0039). |
| `GET /runs?ticker=` | The company's `edgar` and `news` runs from the journal, newest first, in the export's row shape. |
| `POST /analyse` | The only request that makes anything exist. Newline-delimited JSON: `started`, `filing`, one `progress` per stage as the run's trace records it, then `result` — or `failed` with the reason. |

All five check `Host` and `Origin` (ADR 0036 §3). The hosted copy has no server and so
no quote and no two-year window: Yahoo's data is not this project's to republish.
