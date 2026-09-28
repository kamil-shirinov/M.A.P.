# Setup

You only need this to *run* the pipeline. To check the claims, the
[README](../README.md)'s "Verify it yourself" is enough — the test suites need
neither an inference server nor the network.

---

## Requirements

- Apple Silicon Mac (developed on an M1, 16 GB). Models load **one at a time** — the
  pipeline never holds two resident.
- An OpenAI-compatible inference server on `localhost`, with the three configured models
  available. The backend is named only in `config/default.toml`, never in code.
- Python 3.12 exactly. The minor version is pinned (`>=3.12,<3.13`) so a backtest is not
  silently re-run on a different interpreter.

## Setup

```bash
uv python install 3.12
uv sync --extra dev
```

Then set your SEC EDGAR User-Agent — EDGAR returns `403` and blocks the IP for roughly
ten minutes without a descriptive one:

```bash
export MAP_DATA__SEC__USER_AGENT="Your Name your.email@example.com M.A.P. research tool"
```

or edit `data.sec.user_agent` in `config/default.toml`. Startup validation rejects the
shipped placeholder rather than letting you discover the block at runtime.

## Model names differ by backend

The same weights are named differently by every inference server, so the aliases in
`config/default.toml` are an adaptation point, not a fact about the model. They hold
the ids **verified on the reference machine** (LM Studio, 2026-08-11):

| Agent | Verified alias | Shape |
|---|---|---|
| intake | `llama-3.2-3b-instruct` | LM Studio: `publisher/model-name`, or a bare name |
| analyst | `google/gemma-4-12b-qat` | LM Studio |
| structuralist | `qwen/qwen3-4b-2507` | LM Studio |

Ollama names the same weights in `name:tag` form (`qwen3:4b`) rather than
`publisher/model-name`. **The exact strings are not documented here on purpose** —
they depend on which build you pulled, and a guessed alias that happens to match a
different quantisation would silently forecast with the wrong model. Run:

```bash
map health          # prints every id the running server reports
```

and copy the ids it lists. Resolution is **exact-match only** (with a
case-insensitive second pass) — there is no fuzzy fallback, because a near-miss
produces a complete, valid, wrong forecast rather than an error.

To override without editing a tracked file, put your aliases in
`config/local.toml` (gitignored) or export
`MAP_MODELS__STRUCTURALIST__ALIAS=...`.

### Weight pinning is unavailable on some backends

`map health` will tell you when it is. The OpenAI-compatible `/v1/models` endpoint is
not required to expose a weight digest, and on the reference machine it returns only
`id`, `object` and `owned_by` — the last two constant across every model. With
nothing identifying to hash, runs record `fingerprint_source: "tag"`, and a cached
result cannot be pinned to exact weights. Richer metadata exists behind that server's
*native* endpoint; reaching for it would make the code backend-aware, which this
project does not do. See ADR 0001.

## Dependencies

Thirteen at runtime. Every one is named and justified here and in `pyproject.toml`,
per `CLAUDE.md` §2.4 — a dependency that cannot be defended in one line does not
belong in the file.

| Package | Why |
|---|---|
| `pydantic` | All schemas and validators, and the single source of the JSON Schema handed to constrained decoding |
| `pydantic-settings` | `MAP_`-prefixed, `__`-nested environment overlay on the TOML baseline |
| `typer` | CLI |
| `httpx` | The only HTTP client. Its built-in `MockTransport` also removed the need for a mocking library |
| `structlog` | Structured logging; `trace.jsonl` is JSON lines |
| `pandas` | `PriceWindow` converts to a DataFrame at the `mapf.data` boundary; both price sources speak it |
| `pyarrow` | Parquet engine for the price cache — pandas' default, and what Phase 2's columnar reads will want |
| `yfinance` | Primary price source. An unofficial Yahoo scraper, not a supported API — hence the fallback |
| `feedparser` | RSS/Atom dialects vary enough in practice that stdlib `xml.etree` is brittle on real feeds |
| `numpy` | The Monte Carlo mixture, every scoring rule and the moving-block bootstrap. Pure-Python resampling over 4,000 draws on 349 items is not a slower option, it is an infeasible one |
| `scipy` | Normal CDF and PPF for the closed-form CRPS and the PIT. Arrives with `arch` anyway; declared because relying on a transitive dependency is how a build breaks when the intermediary drops it |
| `arch` | The GARCH(1,1) baseline. Hand-rolling a variance model to benchmark against is a bad idea in a project whose point is the benchmark: a poorly fitted baseline flatters M.A.P., and that failure is invisible in the result |
| `plotly` | A single self-contained `chart.html`, no server and no build step |

**Deliberately absent**, where a dependency would have been the obvious choice:

- **Stooq** — the fallback price source is one CSV endpoint, fetched with `httpx`
  and parsed with `pandas`. `pandas-datareader` was dropped because it is a thin
  wrapper over that same URL, intermittently maintained, and sits in the *fallback*
  path — which exists precisely because the primary source is unreliable.
  Inheriting a second package's failure modes there defeats the purpose.
- **Symbol search** — SQLite FTS5 is in the standard library and satisfies the
  search requirement. `rapidfuzz` was dropped; typo tolerance is deferred to Phase 4.

## Development

```bash
uv run pytest                # inference server OFF; network tests deselected
uv run pytest -m network     # opt in to the tests that need network
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run lint-imports          # architecture boundaries — see ADR 0004
node --test ui/tests/*.test.mjs   # the front end; no package.json, no dependencies
node ui/tests/styles.probe.mjs   # computed styles in a real browser; needs Playwright
```

The test suite must pass with the inference server switched off. If it ever needs a live
model, CI is broken.

### Two suites, one repository

`ui/` is the front end, merged in with its own history in 2026-09. It has **no build
step and no dependencies** — ES modules served as files, and `node --test` against a
DOM stub — so it needs nothing installed that the Python side does not already need.

Its tests read `ui/assets/export/`, which is generated and gitignored, and **skip
themselves when it is absent**. A fresh clone therefore passes both suites and exercises
the front end on nothing; `uv run map export` is what makes those assertions real.

### Showing it to someone

A clone **cannot** regenerate the export — `var/` is not committed — so a reviewer who
clones sees the No-export panel. `scripts/build_site.sh` assembles a servable copy into
`site/` and stops; it does not deploy. `docs/publishing.md` covers what the copy
contains, what `--no-prices` leaves out, and what remains third-party either way.

### The CSS blind spot, and the probe that closes it

`node --test` builds the DOM against a stub and **never loads a stylesheet**. That is
the right trade for a suite that runs in milliseconds with no browser, but it means a
whole class of defect is invisible to it, and two have shipped: `system.css` loaded
before the per-screen sheets and was silently outranked, and `company.html` never
linked `runs.css` at all. Both passed every test.

`ui/tests/styles.probe.mjs` opens each page in Chromium and asserts computed values
that can only be right if the right sheets loaded in the right order — a section head's
font family and tracking, a journal row's grid columns, a tag's border, the crest's
size — plus two whole-page invariants: every `<link rel=stylesheet>` actually parsed,
and `system.css` is last. **It is not a pixel diff**, and it fails with the property, the
wanted value and the value it got.

Playwright is **deliberately not a dependency of this repository** — it would put a
300 MB install behind `uv run pytest`. The probe resolves it from outside and exits 2
with instructions when it cannot, so a machine without it skips the check rather than
failing it.

The two halves meet at exactly one place, the export, and `docs/export-contract.md` is
its contract. That is why they are one repository: a change to what the export emits and
a change to the page reading it now land in the same commit or not at all.

### `refs/archive/*`, and what a history rewrite must not touch

`refs/archive/*` pins commits nothing else reaches — today the 25 originals that a
2026-09-08 rebase replaced, including the one `corpus/holdout_spend.jsonl` names.
**Any history rewrite must exclude `refs/archive/*`**, or it rewrites the commits the
ref exists to preserve. See Findings #58; the bundles outside the repository are the
second line.

### Coverage is gated at 100%, and `scripts/` is outside the gate

`addopts` measures `--cov=mapf`, so the gate covers the package and **not** `scripts/`,
which is tracked, linted, type-checked, and untested. That was a fair trade while the
directory held one-off diagnostics. It is worth stating plainly now, because two of the
three scripts there produce output this project has published from:

| Script | What it produced |
|---|---|
| `scripts/ablation.py` | The four-arm ablation — arms A/C/control, 786 runs, reported in the findings and the timeline |
| `scripts/edgar_prescreen.py` | `var/filers/item_202.jsonl` — which SEC filers publish Item 2.02 8-Ks |
| `scripts/backfill_forecast_digest.py` | A one-off repair of stored manifests |

So a result quoted from this project may have come through code the 100% figure does not
describe. The reusable halves live under test in `mapf` — the Item 2.02 item filter in
`mapf.data.filings`, the pipeline in `mapf.pipeline` — and what stays in `scripts/` is
the walking, the sampling and the printing. That is the boundary, not a claim that the
scripts are covered.

---
