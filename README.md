# M.A.P. — Market's Agentic Predictor

Turns unstructured financial news into **calibrated, falsifiable probabilistic price
forecasts** using local open-weight models. Three specialised agents run in sequence;
the output is a schema-validated JSON forecast plus a chart.

> **Status: Phase 1 code complete, first live run in progress.** All eight acceptance
> criteria pass as tests against recorded fixtures, with no inference server and no
> network. What has *not* yet happened is a full run against a real backend — so no
> claim is made here about forecast quality, and none should be inferred. The prompts
> have been tested for structure, never for whether a 3B model produces useful facts.

---

## What this is not

**This is not financial advice, and it is not a trading system.** No order execution, no
broker integration, no position sizing. It is a research and engineering exercise whose
purpose is to produce forecasts that can be *scored* — a forecast that cannot be scored
is a bug, not a feature.

---

## Honest claims

Four things are easy to overstate about a project like this. The accurate versions:

**All *inference* is local.** No data is sent to a third-party model provider. This is
**not** "100% offline": price data comes from Yahoo Finance or Stooq over the network,
the symbol universe is downloaded from SEC EDGAR, and news may be fetched from RSS.
Those are third parties, and they see what you ask for.

**Training-cutoff leakage makes naive backtests worthless.** The models already know what
happened to well-known tickers. Any backtest run on news published before a model's
training cutoff is contaminated, and a *good* result from such a backtest is evidence of
memorisation, not of forecasting skill. Phase 2's evaluation harness is designed around
this from the start. Treat any pre-cutoff result as invalid until proven otherwise.

**Name search covers US-listed companies only.** The searchable symbol universe comes
from the SEC's `company_tickers_exchange.json` (~10k US-listed companies). Non-US
listings work only if you already know the suffixed ticker (`.L`, `.TO`, `.DE`); they do
not appear in name search. There is no global name coverage.

**"Reproducible" is four separate claims here. Three hold; the fourth does not.**

| claim | verdict |
| --- | --- |
| **Pre-registered** — the corpus, the bands and every threshold were fixed before any result was seen | **holds**, and the commit order proves it |
| **Auditable** — every prompt and every raw response is preserved in `runs/<run_id>/trace.jsonl` | **holds**; a run is refused if any trace is missing or empty |
| **Replayable from cache** — re-reading a completed run returns byte-identical output | **holds** |
| **Re-derivable** — a cold cache reproduces the same forecasts | **does not hold** |

Agents 1 and 3 request `temperature=0` and a fixed seed, and every run records the
seed, the sampling parameters and the model fingerprint *as requested* — many local
inference servers ignore both. **Temperature 0 is near-deterministic, not
deterministic, on this backend, and that is measured rather than assumed: replaying
five identical recorded prompts returned byte-identical output twice out of five.**

So a re-run from a cold cache produces *similar* forecasts, not identical ones. What
is exact is replay **from the cache** — which is why the cache is provenance
infrastructure and not an optimisation.

**The quality checks read prose, not the forecast.** Every run records whether figures in
a scenario's *justification* trace back to a material fact. That check does **not** cover
`price_return`, `annualised_vol` or `probability_weight` — the numbers actually scored.
Nothing grounds those against the source, and nothing could straightforwardly: a forecast
is supposed to state something the source did not. Their only checks are the schema's
bounds and the ordering invariant. Read a clean `ungrounded_numerals` as "the prose cites
nothing invented", never as "the forecast is supported".

The three-agent architecture is a **hypothesis**, not a result. Whether it beats a
single-agent baseline is an open question that Phase 3's ablation study exists to answer.
Nothing here claims it is better.

---

## What Phase 1 does not guarantee — an incident

The first live run produced a forecast that passed every check in this project and
contained a figure the model invented. It is worth reading in full, because it is
the clearest available statement of what the machinery here is and is not for.

The source article said Apple's gross margin was **46.3%**. Agent 1 extracted that
correctly. Agent 2 reasoned about it correctly, quoting 46.3% twice. Agent 3, while
transcribing that reasoning into the structured forecast, wrote:

> "the high gross margin of **66.3%** suggests a stable profit floor"

Nothing caught it. The output was valid JSON under a constrained grammar. Its three
probability weights summed to 1.0. Its scenarios were correctly ordered. Every
field was inside its bounds. The repair loop was never triggered because there was
nothing to repair. 489 tests passed, `mypy --strict` passed, four architectural
contracts held. The forecast was written to disk, charted, and reported as a
success — **and one of the premises underneath it did not exist.**

That is not a bug that was fixed. **It is the failure mode this project is
structurally unable to detect**, and it is documented in `mapf/agents/__init__.py`
in exactly those terms, written before it happened:

> A forecast can be schema-valid, internally consistent, fully traced, and built
> entirely on a premise the model invented. […] Nothing here detects that, because
> nothing here compares the forecast to reality.

The same run also produced three scenarios spanning 0.15% — a "bullish" case of
+0.05% over 21 days, for a stock that routinely moves several percent in that
window. Also valid. Also unremarked.

**What changed as a result:** a crude numeral check now flags figures in a
justification that trace back to no extracted fact, and a spread check flags
scenarios that cluster too tightly for their horizon. Both are **warnings recorded
in the manifest, never rejections** — a model paraphrasing "46.3%" as "about 46%"
must not fail a run, and a genuinely flat outlook is a legitimate forecast. Neither
check is reliable. Both convert an invisible failure into a visible one *some* of
the time, which is the entire claim being made for them.

**What did not change, and cannot:** nothing here verifies that a forecast is
*right*. Validators guarantee internal consistency. Grammars guarantee shape.
Neither has any access to whether the numbers mean anything. That is Phase 2's job
and only Phase 2's — which is why a forecast that cannot be scored is treated in
this project as a bug rather than a feature.

The forecasts this system produces are **falsifiable, not verified.** The incident
above is the evidence for that distinction, not an exception to it.

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

## Development

```bash
uv run pytest                # inference server OFF; network tests deselected
uv run pytest -m network     # opt in to the tests that need network
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run lint-imports          # architecture boundaries — see ADR 0004
```

The test suite must pass with the inference server switched off. If it ever needs a live
model, CI is broken.

---

## A documented property: the probability-weight tolerance

Scenario weights must sum to `1.0`. They are checked with a tolerance of `1e-6`
rather than for equality, and the tolerance is load-bearing — not a convenience.

Three decimal weights are not exactly representable in binary, so the sum depends
on the order the branches are added:

```
0.1 + 0.2 + 0.7  ==  1.0
0.2 + 0.7 + 0.1  ==  0.9999999999999999
```

An equality check would accept or reject the same forecast depending on which
branch happened to be added first. The error here is ~1.1e-16, far inside the
tolerance, so behaviour does not actually change — but it shows why the tolerance
has to exist.

The tolerance also has an **asymmetric boundary**, and this is worth stating
plainly because it looks like a bug and is not:

```
0.25 + 0.60 + 0.150001  →  |sum - 1| = 9.99999999917733e-07   accepted
0.25 + 0.60 + 0.149999  →  |sum - 1| = 1.00000000002876e-06   rejected
```

The same nominal deviation of `1e-6` is accepted above `1.0` and rejected below
it. Neither computed value *is* `1e-6`; both are the nearest representable double,
and they land on opposite sides of the comparison. This is a property of binary
floating point, not of the validator, and it cannot be tuned away — **any**
threshold has an edge that behaves this way. Moving to `math.isclose` would
relocate the asymmetry, not remove it.

Both properties are pinned in `tests/unit/test_scenario_validators.py`, so a change
to the comparison shows up as a failing test rather than as a silent shift in which
forecasts are accepted. No other test depends on the exact boundary.

## Dependencies

Ten at runtime. Every one is named and justified here and in `pyproject.toml`,
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
| `plotly` | A single self-contained `chart.html`, no server and no build step |

**Deliberately absent**, where a dependency would have been the obvious choice:

- **Stooq** — the fallback price source is one CSV endpoint, fetched with `httpx`
  and parsed with `pandas`. `pandas-datareader` was dropped because it is a thin
  wrapper over that same URL, intermittently maintained, and sits in the *fallback*
  path — which exists precisely because the primary source is unreliable.
  Inheriting a second package's failure modes there defeats the purpose.
- **Symbol search** — SQLite FTS5 is in the standard library and satisfies the
  search requirement. `rapidfuzz` was dropped; typo tolerance is deferred to Phase 4.

## Documentation

| Document | What it holds |
|---|---|
| `CLAUDE.md` | Working agreement, hard constraints, architecture rules |
| `M.A.P.-vault/STATE.md` | Where the project actually is. Read this second |
| `M.A.P.-vault/decisions/` | ADRs — every non-obvious choice, with the alternatives rejected |

---

## Licence

Not yet chosen.
