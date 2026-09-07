# M.A.P. — Market's Agentic Projections

Turns unstructured financial news into **calibrated, falsifiable probabilistic price
forecasts** using local open-weight models. Three specialised agents run in sequence;
the output is a schema-validated JSON forecast plus a chart.

> **Status: Phases 1 to 3 complete.** 701 forecasts across two years of filings on a
> pre-registered corpus. The system's stated uncertainty was measured, found to be too
> narrow, corrected by a two-parameter map fitted on half the data, and the correction
> was tested once on the other half — where it improved both scoring rules on data it
> had never seen. The forecasts themselves remain worse than a random walk. The
> holdout has been spent and cannot be spent again.

---

## Results

The corpus was frozen and committed before any inference ran; the commit order is the
pre-registration. **356 filings from after the models' training cutoff and 353 from
before it**, 120 companies, 8-K Item 2.02 exhibits, a five-session horizon, point-in-time
aligned so the overnight announcement gap falls outside the window.

**701 forecasts completed. 8 failed** — every one an agent generating its full token
budget and emitting no answer. All are named in `M.A.P.-vault/`.

> **Log score is the negative log predictive density: lower is better.** Stated because
> "improved from −0.949 to −1.237" reads as worse to almost every reader.

### Phase 2 — the measurement

Development half, **175 items in 18 date clusters**, cluster-robust intervals throughout.

| | vs random walk | vs GARCH | vs earnings-scaled RW |
| --- | --- | --- | --- |
| CRPS | worse by 5.4% | indistinguishable | indistinguishable |
| Log score | worse by 12.9% | worse by 12.0% | indistinguishable |

**Calibration ratio 0.733, 95% CI [0.637, 0.801].** The interval excludes 1.0, so the
over-confidence is measured rather than suspected. This was the question the phase was
redesigned around after a power analysis showed directional skill was undetectable at
any affordable sample size.

**Directional accuracy 49.7%** (87 of 175). P(up) spans 0.369 to 0.631 with a median of
0.513 — the system does not so much get direction wrong as decline to have a view. All
three baselines set mean zero by construction and score identically, so this is a
comparison against a coin.

**No measurable training-cutoff leakage.** Clean band 0.0318 against ambiguous 0.0335, a
difference of **−0.0017 with an interval from −0.0093 to +0.0060**. The system scores
marginally worse on the filings it might have memorised — the direction that embarrasses
the contamination hypothesis rather than supporting it. This design could have detected
gross memorisation and could not have detected a subtle familiarity effect of a few
percent, and this sentence is the write-up saying so.

### Phase 3 — the correction, and the one-shot test

A two-parameter map `z → (z − a) / b`, fitted on the development half only, by minimising
the log score. Form, objective, success condition and predicted failure mode were all
committed before the fit ran.

Fitted: **a = −0.076** (covers zero, as predicted — there was no directional tilt to
remove), **b = 1.331** (excludes 1, so the intervals genuinely needed widening).

**The pre-registered success condition failed on development.** The corrected body came
out over-dispersed, which is the exact failure mode recorded in advance: a scale fitted
to the log score lets a handful of extreme items pull it up and over-widen the ordinary
ones.

The holdout was then spent, once, on **173 items**.

| | corrected | uncorrected | difference |
| --- | --- | --- | --- |
| Log score | **−1.237** | −0.949 | **−0.288 [−0.453, −0.111]** |
| CRPS | **0.0378** | 0.0387 | **−0.0009 [−0.0018, −0.0001]** |

Both intervals exclude zero. **The correction generalises to data the fit never saw.**

Corrected, the calibration ratio moves from 0.592 to 0.788 and the body's dispersion from
1.380 to 1.037, an interval covering 1.0. The tail ratio does not move — 1.175 to 1.183 —
exactly as predicted, because a location-and-scale map cannot change kurtosis.

**Two claims that must not be merged.** The calibration correction generalises out of
sample. The forecasting did not improve: corrected, the system now beats the
earnings-scaled random walk on CRPS, and still loses to GARCH and to the plain random
walk on both rules. *A better-calibrated statement of the same information is not a
better forecast.*

**And the development failure was not refuted.** The condition failed on development by
0.0069 and passed on the holdout — but the two halves are not distinguishable from each
other. The difference in their uncorrected calibration ratios is **+0.100 with an
interval from −0.065 to +0.249**, and the same holds for every dispersion statistic
compared across the split. Two marginal calls landing on opposite sides of 1.0 in samples
a test cannot separate. The defensible statement is that the correction is approximately
right, and whether it slightly over- or under-corrects is unresolved at this sample size.

### Registered replications

Two findings developed on the development half were given pre-registered replication
tests on the second band, written before any of its items were scored.

**Cross-sectional volatility compression: replicated**, against both baselines. The
system's volatilities span about half the range a trailing-volatility baseline does — an
attenuation-corrected slope near 0.4 where 1.0 is correct, with every registered
prediction met and the effect monotone across three cut depths. This is the project's
only finding established out of sample.

**Heavier-than-normal tails: partial.** The exceedance counts replicated emphatically;
the tail ratio's interval missed excluding 1.0 by 0.005. Registered in advance as a
possible split outcome, and reported as a miss rather than rounded. The Student-t
successor it would have triggered stays unadopted.

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

**Nearly two-thirds of the clean band cannot be reconstructed from a commit.** 208 of
351 completed items were produced while the working tree had uncommitted changes, so no
code digest was recorded. Development continued against a live run for days, which was a
mistake. The honest figure is **214 of 349 at the moment the band finished**; correcting
an unrelated defect later happened to clean six. The second band has none — **350 of 350
carry one digest at one commit** — so the defect was fixed rather than merely survived.

What survives this: the forecast-governing surface was verified against the frozen record
at every launch. What does not: that verification did not cover the truncation
parameters, one of which drifted mid-band under an unchanged identifier, affecting six
items that were found and re-run.

**The price vintage pinned nothing until 5 September 2026.** Every manifest recorded
`fetched_on: 2026-08-14`. No price was ever fetched on that date. The cache was keyed on
the real calendar day in every code path, so the corpus was built across at least seven
daily snapshots while every manifest asserted a single one that never existed. What
protected the result was not the pin but a drift guard written for a different purpose,
which refuses to score an item whose recorded spot has moved. The corpus now exists at
one deliberately pinned snapshot of **701 windows** — the first time in the project's
history that has been true.

**"Reproducible" is four separate claims here. Three hold; the fourth does not.**

| claim | verdict |
| --- | --- |
| **Pre-registered** — the corpus, the bands and every threshold were fixed before any result was seen | **holds**, and the commit order proves it. **Twenty-two pre-registration records** are stored as git notes on `refs/notes/commits`, each written before the result it constrains. GitHub does not display notes in the web interface — read them with `git log --show-notes`. They fix the statistics, the predicted direction, and the interpretation of every outcome including those that would disconfirm |
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

**Measured at the level of results, not strings.** A cold re-run of the whole
pipeline on 60 items leaves the aggregate unmoved — mean CRPS 0.03255 cached against
0.03240 cold, a paired difference of −0.00016 with an interval from −0.00072 to
+0.00066 — while **individual items shift by 4.3% on average and 53% come back
byte-identical**. So non-determinism is real and visible per item, and it does not
move the reported means. Both halves of that are worth stating: the first is why
"re-derivable" fails, the second is why the published figures are nonetheless
stable.

**Scoring was non-reproducible for a second, unrelated reason.** Until the vintage was
pinned, prices were re-fetched on every run, and an upstream split or correction rewrites
history retroactively. Three items were lost to a genuine SCCO split the provider applied
25 days late. Note that dropping those items is *conservative rather than correct* — a
return is scale-invariant under a split, so they are scoreable once the recorded spot is
rescaled. The guard refuses because it cannot distinguish a split from genuine drift.

**One phase opened without its criteria committed.** Phase 1's eight acceptance criteria
were committed in the initial commit, before a line of `src/` existed. **Phase 2's seven
were never committed at all.** They were written in advance, in a brief that only ever
existed as a chat message, and by the standard applied everywhere else here — git history
is the pre-registration — that is the same as not having them. Every decision made
*during* the phases was committed as it happened: thirty-three ADRs and fourteen
timestamped notes. The gap was in the opening statement only, and Phase 3 opened with its
criteria committed.

**The quality checks read prose, not the forecast.** Every run records whether figures in
a scenario's *justification* trace back to a material fact. That check does **not** cover
`price_return`, `annualised_vol` or `probability_weight` — the numbers actually scored.
Nothing grounds those against the source, and nothing could straightforwardly: a forecast
is supposed to state something the source did not. Their only checks are the schema's
bounds and the ordering invariant. Read a clean `ungrounded_numerals` as "the prose cites
nothing invented", never as "the forecast is supported".

**The three-agent architecture is a hypothesis, and the ablation that would have
tested it could not be run.** Four arms were pre-registered; two of them — both
requiring the 12B model to work inside a token budget — failed identically and were
abandoned. Losing one of them lost both primary comparisons, so **the ablation has no
primary and makes no causal claim**. What survives is descriptive: the full pipeline
beats a no-analyst variant by 13.6% on CRPS, and three things differ between them
(the analyst, the model size, and necessarily the prompt), so "the analyst helps" is
one of three readings the design cannot separate. Nothing here claims the
architecture is better.

**Why the arms failed is the more useful result.** A reasoning model spends its
budget on reasoning first and the answer last, so capping the budget truncates the
output rather than the deliberation. At 1,000, 12,000 and 15,000 tokens — the last
being the most a 16,384-token window allows — roughly **99.98% of the allowance went
to reasoning and no answer was produced**, every time. *A reasoning model's cost is
not tunable by its budget*, and it does not drop into a fixed-budget pipeline slot.
It can be made cheaper only by removing the agent, by choosing a model that reasons
less, or by a provider-side reasoning-effort control this backend does not expose.

**The corpus is a reusable benchmark.** 709 filings identified by accession number, with
recorded outcomes, two baselines scored, a frozen protocol and a pinned price snapshot.
Any future model can be run against the identical panel with one configuration change,
because the backend is named only in configuration and never in code.

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

Copyright (c) 2026 Kamil Shirinov. All rights reserved. You are welcome to
read this code; it is not licensed for reuse.
