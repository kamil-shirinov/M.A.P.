# M.A.P. — Market's Agentic Predictor

Turns unstructured financial news into **calibrated, falsifiable probabilistic price
forecasts** using local open-weight models. Three specialised agents run in sequence;
the output is a schema-validated JSON forecast plus a chart.

> **Status: Phase 1, in progress.** The domain layer (`mapf.core`) is built and tested.
> No agent, provider, or CLI exists yet — `map run` does not work. This README describes
> the target and the constraints, not a finished tool.

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

**Determinism holds where the backend honours it.** Agents 1 and 3 request
`temperature=0` and a fixed seed, and every run records the seed, sampling parameters and
model fingerprint. Many local inference servers ignore `seed`, and some do not
implement `temperature=0` deterministically. The manifest records what was *requested*.
This is reproducible-where-supported, not reproducible.

The three-agent architecture is a **hypothesis**, not a result. Whether it beats a
single-agent baseline is an open question that Phase 3's ablation study exists to answer.
Nothing here claims it is better.

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

## Documentation

| Document | What it holds |
|---|---|
| `CLAUDE.md` | Working agreement, hard constraints, architecture rules |
| `docs/STATE.md` | Where the project actually is. Read this second |
| `docs/decisions/` | ADRs — every non-obvious choice, with the alternatives rejected |

---

## Licence

Not yet chosen.
