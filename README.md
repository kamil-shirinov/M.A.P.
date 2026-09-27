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

### How 10,398 tickers became 120 companies

Every narrowing below is a recorded artifact, not a description written afterwards.

| | count | what removed the rest |
|---|---|---|
| Tickers in the SEC index | **10,398** | — |
| Distinct filers behind them | **7,998** | 2,400 are share classes and dual listings of the same CIK |
| Filers with an Item 2.02 8-K in their recent block | **4,325** (54.1%) | 3,673 publish no earnings 8-K: funds, trusts, dormant registrants |
| Tickers belonging to one of those filers | **5,309** (51.1%) | — |
| Tickers examined by the seeded selection walk | **1,181** | the walk stops once the target is met; 6,478 were never reached |
| **Companies accepted into the frozen corpus** | **120** | 716 illiquid, 324 no price history, 19 no exhibit, 2 duplicate CIK |
| Filings held for them | **709** | — |
| Filings with a completed run | **701** | 8 failed terminally, and are exported with an empty run list rather than dropped |

The 54.1% is measured, not estimated: `scripts/edgar_prescreen.py` walked all 7,998
filers on 2026-09-09, one request each, and wrote `var/filers/item_202.jsonl`. An
earlier name-keyword guess at the same question was wrong about **15%** of what it
flagged — "Trust" and "Shares" are as common in REITs and banks as in funds.

Two numbers in that table are easy to misread. **1,181 is not a rejection rate**: the
selection walk stops when it has enough companies, so the 6,478 unreached tickers are
untested rather than failed. And **709 versus 701** is why the export carries every held
filing with an explicit run list, empty where nothing ran — a page showing 701 would
misstate the corpus it is drawing.

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
difference of **−0.0017 with an interval from −0.0093 to +0.0060**. Both halves are now
persisted scoring records, so that difference is re-derivable rather than quoted: mean
CRPS **0.03179** on 175 clean/dev items against **0.03348** on 174 ambiguous/dev items is
**−0.00169**, reproducing the published figure from artifacts. The system scores
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

### What survives of the holdout, and what does not

**The holdout's per-item scores were not persisted and cannot be recovered.** They were
computed once, printed once, and are gone.

That is correct, not an oversight. `map evaluate --split holdout` is refused *before
anything is computed* once the spend is recorded (ADR 0031), and it is recorded — so
there is no re-run that could produce them, and adding one would mean defeating the
guard. A holdout scored twice is not a holdout.

What survives is in `corpus/holdout_spend.jsonl`, which is **tracked**, so its git
history is the record of the single spend:

- the calibration coefficients — `a = −0.0757`, `b = 1.3305`, `form: z → (z − a) / b`
- what it was fitted on, its ADR, and the notes that amended it
- the band, the item count (173), the date, the commit, the freeze version and the
  price vintage

The band-level results are the table above. Everything else — the 173 individual CRPS,
log-score and PIT values — existed only in one terminal session.

**One band-level result is stated, not verifiable.** The comparison against the three
baselines — pre-registered as secondary measure S5, for both the corrected and the
uncorrected forecast — survives only as the sentence in Phase 3 above: better than the
earnings-scaled random walk on CRPS, losing to GARCH and the plain random walk on both
rules. Every other secondary measure has its figures and intervals in the Development
Timeline. S5 has no figure and no interval in any artifact; the sentence does not say
whether "loses" means an interval excluding zero, and two of its twelve comparisons are not
stated at all. The same comparison on the development half is persisted with its intervals,
under `var/corpus/scores/` and in the export. See Findings #57.

Development-half scoring passes *are* persisted, under `var/corpus/scores/`, because dev
is re-scoreable. So the asymmetry in this repository is deliberate: you can re-derive any
development number from an artifact, and no holdout number.

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

### Phase 4 — what a reader can verify without re-running anything

Phase 4 built read paths, not results. None of it is new evidence about forecasting.

**What you can check, and with what.** The Phase 1–3 results above are verifiable from
this repository alone: `corpus/frozen.json` is the pre-registration and its commit order
is the proof, and `corpus/holdout_spend.jsonl` is the record of the single holdout spend.
Phase 4's *structure* is verifiable from the source and the test suite — that the journal
cannot compute a score, that populations have no pooled accessor, that a scoring record
refuses to be overwritten. Phase 4's *numbers* are not: 779 runs, 701/74/4, 777 closed,
5.34 MB all come from `var/` and `runs/`, which this repository does not ship. Clone it
and `map export --allow-partial` writes 0.09 MB — the corpus and nothing else.

That boundary is the honest claim. A reader can confirm the machinery does what is
described here; only someone with the artifacts can confirm the counts.

**`map export`** writes the whole readable state as flat JSON into `ui/assets/export` — 5.34 MB, of
which 0.77 MB is eager. No server, no dependency. **`map export --check`** re-derives
the identity of all seven inputs and names what has moved since the export was written,
because a copy goes silently behind and a date alone does not make that visible.

**`map runs`** is the run journal: 779 readable runs of 826 directories, each with its
anchor, the three scenarios it produced, and what the price did. Nothing in it computes
across a forecast and its outcome — no error, no return, no hit — and the type offers no
member that could (ADR 0035). 47 directories it cannot read are counted and reported
rather than dropped.

**`corpus_relation`** tells three cases apart that were previously one:

| | runs | what it means |
|---|---|---|
| `ledger_item` | **701** | the ledger maps this run to a frozen corpus item |
| `repeat_of_exhibit` | **74** | the document is a frozen exhibit; the run is not the ledger's run for it — a re-run, a post-band repeat, an ablation replay |
| `outside_corpus` | **4** | the document is not one the corpus froze |
| `unchecked` | **0** | (779, when no frozen record or ledger is supplied) |

The 74 are 10% of the log and were previously indistinguishable from panel items.
Note also that `ledger_item` is **not** a claim that an item was scored: a ledger entry
promises artifacts exist, and no per-item score is persisted for any holdout item.

**Outcomes are retrieved, never stored**, from the pinned 2026-09-05 snapshot — with the
snapshot named, the provider read from the parquet's own metadata, and the retrieval
date. A run's own vintage ends at its anchor and structurally cannot hold its outcome.
Each run gets one of four answers, never an omission: **777 `closed`, 2 `window_open`,
0 `absent_from_snapshot`, 0 `not_requested`**.

**Development scoring passes persist** to `var/corpus/scores/`, write-once per (band,
split, vintage, code digest) — identical content left alone, differing content refused
rather than overwritten. Two records exist today and both are exported: one from a
committed tree and one from a dirty tree that no longer exists. That is the design, not
clutter — a regeneration under changed conditions lands beside its predecessor.

**The holdout has no such record and cannot**, for the reason given above. The export
states that as a fact in its manifest rather than leaving a missing file to be noticed.

The front end is `ui/`, in this repository, and reads that export — four screens over
the real files, with no fixture behind any figure on them.

### Phase 5 — the ablation, and what remains designed

**Four arms were planned; two produced comparable numbers.**

**A − C = 13.6% on CRPS**, interval well clear of zero, on 355 paired items. It is
**descriptive, not causal**, and the design separates none of the three confounds:

1. the **analyst** is removed;
2. the **model** doing the forecasting changes from a 12B to a 4B;
3. the **prompt** changes, necessarily — the frozen structuralist's first rule is to
   copy the estimate numbers from the narrative, and with no analyst there are none,
   so 11 of 25 lines had to change.

Arm D existed to separate (1) from (2) and could not be made to run. So *"the analyst
helps"* is one of three available readings and the experiment cannot say which.

**Arm D was shown infeasible, not declined.** Every failure was the same shape: the 12B
generating its entire budget as reasoning and emitting no answer. The first rejection
was methodological — 12,000 tokens was a cap, not a wall, with 3,610 tokens of headroom
unused. A ten-item probe at **15,000 tokens**, the largest the 16,384 window allows,
registered in advance with both readings fixed: **ten of ten failed**, seven exhausting
the budget and three unable to fit the prompt at all. Given every token the window
physically allows, the model does not finish — so raising the budget is not an option
that was declined, it is an option that does not exist.

**An unpredicted result:** removing the analyst moved **median P(up) from 0.513 to
0.755**. The system becomes markedly more bullish and more opinionated without the
reasoning stage. Nothing in the pre-registration anticipated this, and it is reported as
unpredicted rather than folded into the CRPS story.

**Everything else in the Phase 5 design document is designed and unbuilt.** Of its six
parts, exactly one — A1, the ablation — has been executed. Not built: trailing realised
volatility as an input (A2), prior guidance from the previous 8-K (A3), the horizon
ladder beyond five sessions (B), the long-term head (C), scenario mode (D), and the
surface work including per-forecast caveats and a generated architecture diagram (E).
The document describes intentions; this paragraph exists so a reader does not mistake it
for a record of work done.

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
| **Pre-registered** — the corpus, the bands and every threshold were fixed before any result was seen | **holds**, and the commit order proves it. **Twenty-two pre-registration records** are stored as git notes on `refs/notes/commits`, each written before the result it constrains. They fix the statistics, the predicted direction, and the interpretation of every outcome including those that would disconfirm. **Verify them yourself — see below** |
| **Auditable** — every prompt and every raw response is preserved in `runs/<run_id>/trace.jsonl` | **holds**; a run is refused if any trace is missing or empty |
| **Replayable from cache** — re-reading a completed run returns byte-identical output | **holds** |
| **Re-derivable** — a cold cache reproduces the same forecasts | **does not hold** |

### Verifying the pre-registrations yourself

**GitHub does not display git notes in its web interface, and `git clone` does not
fetch them.** They are not in the repository you get by default; you have to ask for
the ref.

```
git fetch origin 'refs/notes/*:refs/notes/*'
```

**The ordering evidence is the ref's own commit history, not the note's contents.**
Each record was appended in a separate operation, so the ref carries one commit per
record, each with the timestamp at which that record was written:

```
git log --format='%h %ad %s' --date=iso refs/notes/commits
```

Twenty-two commits, oldest last. Compare any record's timestamp against the commit
that produced the result it constrains — `git log --format='%h %ad %s' --date=iso
main` — and the claim "written before the result" is checkable rather than asserted.
A record appended after its result would show it here, and that is the point of
keeping them in a ref whose history cannot be rewritten without the rewrite being
visible.

Then read them:

```
git notes --ref=commits show ad71b13
```

All twenty-two are one note on that commit, about 120 KB. `git log --show-notes`
displays it inline against the commit it annotates.

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
structurally unable to detect**, and it is documented in `src/mapf/agents/__init__.py`
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
