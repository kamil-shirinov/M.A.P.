# M.A.P. — Market's Agentic Projections

**The forecasts are the demo; the evaluation is the point.** Three open-weight models,
running locally, read a company's earnings filing and forecast its share price five
trading days out — as a distribution, not a single number. Each forecast was then scored
against what the price actually did. The corpus was frozen before any forecast on it was
made, each test was fixed before its result existed, every result is reported, and the
headline is negative: **it does not beat a plain random walk or GARCH on the development
companies.**

**[→ Open the app](PLACEHOLDER_URL)** — the run journal and the scored results, every
figure marked with where it came from.

*Published for review. No licence is granted for reuse — see [Licence](#licence).*

---

## How it works

Three agents in sequence, each a contract rather than a model — swapping the model
behind one is a config edit:

| | Role | Model |
|---|---|---|
| 1 | Compress the filing into dense material facts | Llama 3.2 3B |
| 2 | Three-scenario reasoning | Gemma 4 12B |
| 3 | Narrative → schema-valid JSON | Qwen3 4B |

Agent 3 is deliberately small: with JSON-schema constrained decoding the sampler makes
invalid tokens unreachable, so model intelligence is not what makes the output valid.

The scenarios become a Monte Carlo distribution. That is scored against the realised
close with CRPS, log score and Brier, against three baselines — a random walk, a GARCH
fit, and a random walk widened for earnings days.

**All inference is local.** No data goes to a third-party model provider. This is *not*
"100% offline": prices come from Yahoo Finance and filings from SEC EDGAR, and those
parties see what is asked of them.

### Live analysis

`uv run map serve` adds the one thing that is not a read of the record: type a ticker,
and it fetches that company's latest earnings 8-K, runs the three agents over it, and
draws the forecast fanning out from the latest close. A run usually takes six to twelve
minutes and is a permanent entry in the run journal. **It only runs on a machine with the
models on it**; the published site is static files and says so.

Most live fans are drawn **raw and marked uncalibrated**. The correction below was tested
on a panel — five sessions, anchored within one trading day of a filing, companies the
corpus filters accept — so it is applied only where all three hold, and the screen names
whichever does not. Even then the run is not one of the frozen panel's items: applying
the correction is defensible, not verified. [ADR 0036](decisions/0036-live-analysis.md).

---

## What it found

**It does not beat a plain random walk or GARCH on the development companies.**

| On 175 clean-band development items | M.A.P. | random walk | GARCH |
|---|---|---|---|
| CRPS *(lower is better)* | 0.03179 | 0.03016 | 0.03105 |
| Log score *(lower is better)* | −1.3786 | −1.5826 | −1.5659 |
| Direction | 87 of 175 — **49.7%** | a coin | a coin |

Against the random walk the CRPS gap is **+0.00163 [+0.00071, +0.00278]** and the log
score gap **+0.2040 [+0.08004, +0.36396]** — both intervals exclude zero, both in the
wrong direction. Against GARCH, CRPS is indistinguishable and the log score is worse.
Against a random walk widened for earnings days, CRPS is −0.00100 [−0.00222, +0.00111]:
better as a point estimate, not established.

Four more things were measured. Every figure below has its interval and its sample in
**[docs/results.md](docs/results.md)**.

**1. The stated uncertainty was too narrow. A correction fixed that on unseen data —
after failing its own test.** The forecasts claimed intervals about 27% tighter than the
outcomes justified (calibration ratio 0.733, where 1.0 is calibrated). A two-parameter
correction, shift and widen, was fitted on the 175-item development half of the clean
band. **Its pre-registered success condition failed on development.** Nothing in the
record said whether a failed condition still spends the holdout, so Kamil decided, having
seen the failure, and that judgement is recorded in git note record 12. The holdout was
spent once, on the other 173 items:

| On the 173 holdout items | corrected | uncorrected | difference |
|---|---|---|---|
| Log score | **−1.23725** | −0.94947 | **−0.28778 [−0.45255, −0.11117]** |
| CRPS | **0.03782** | 0.03873 | **−0.00090 [−0.00178, −0.00012]** |

Both intervals exclude zero: the correction generalises to data it was not fitted on.
Differences are taken before rounding, so a row need not subtract exactly — 0.03782 −
0.03873 reads as −0.00091. **The correction does not make the forecasting better.** Its
comparison with the baselines on the holdout, pre-registered as S5, survives only as a
sentence — corrected, it beats the earnings-scaled random walk on CRPS and still loses to
GARCH and the random walk on both rules — with no figure or interval in any artifact
([Findings #57](notebook/Findings%20&%20Incidents.md)).

**2. No measurable training-cutoff leakage.** The corpus is split into filings from after
the models' training cutoff (clean) and before it (ambiguous). Models remembering rather
than forecasting would score better on the ambiguous half. They do not: **−0.00169
[−0.0093, +0.0060]** on mean CRPS.

**3. The tails are heavier than a normal distribution allows — and that replication was
only partial.** Outcomes land beyond 2.5 standard deviations about five times as often as
a normal predicts. That was pre-registered as a test on the second band, requiring both
the exceedance counts and a tail ratio whose interval excludes 1.0. **The counts
replicated; the ratio missed**, its interval reaching down to 0.9945 — short of the bar by
0.0055. Recomputed from the pre-registration weeks later on the same 177 items, the
interval matches the recorded one at both ends ([Findings #61](notebook/Findings%20&%20Incidents.md)).
The Student-t successor it would have triggered was not adopted. On the same outcomes the
two normal-tailed baselines pass three sigma far less often, so the excess looks like
M.A.P.'s — *quoted from the record; the export does not store the baselines' σ, so this
cannot be re-derived from it.*

**4. One finding did replicate, out of sample: volatility compression.** M.A.P. states too
narrow a range of volatilities across companies — about right for typical names, far too
narrow for the ones that move. On development, the slope of log σ(M.A.P.) on log σ(random
walk) is **0.3166 [0.2609, 0.3811]**, where 1.0 would be right. On the second band the
pre-registered, attenuation-corrected slope came out **0.409 against the random walk and
0.327 against GARCH**, both intervals excluding 1.0 — a different estimator, so the two
are not comparable to each other, only to 1.0. It is the candidate explanation for both
the heavy tails and the narrow intervals.

**What this is not.** Not trading advice, not a signal, not a product. No order execution,
no position sizing, no broker integration. It is an engineering and methodology exercise
whose result happens to be negative.

---

## Why the negative result is the point

A forecasting system that cannot be scored is not a forecasting system. Most of the work
here is in making the claims falsifiable and then letting them fail:

- **The corpus was frozen before any forecast on it was made** — 120 tickers and 727
  forecasts at commit `36e08a3`, 2026-08-14 11:41 UTC, *"FREEZE THE CORPUS --
  pre-registration artifact"*. *Not* before any inference: the pipeline was built and
  exercised on sample documents from 2026-08-11. One of those runs, `266aa3ba`, predates
  the manifest format and cannot be read; four others — AAPL, made on 2026-08-12 and
  2026-08-13 — are in the run journal, marked outside the corpus, and in no scored
  population.
- **Membership was amended once, the same day, before any forecast on the corpus** —
  commit `96ad926`, 16:46 UTC, five hours after the freeze. A pre-flight fetch found **30
  of 727 items had no usable Exhibit 99.1**, over the 2% failure allowance. `BRK-A` was
  dropped as a duplicate CIK with `BRK-B`, and `GEN` for carrying no EX-99.1 on any filing;
  `CG` and `WULF` replaced them from the seeded ordering. **727 forecasts → 709.** This
  applied the pre-registered replacement rule rather than a new one: how a company attaches
  its release is a fixed property of how it files. [ADR 0018](decisions/0018-corpus-band-and-panel-shape.md)
  records the amendment as preceding "all inference", which here means all inference on
  the corpus, and heads the section 2026-08-15 although both commits are dated the 14th.
  `36e08a3` was kept rather than rewritten, so the pair shows what was known when.
- **Later amendments changed how items were run, not which items.** The 779 runs made
  before live analysis span **four freeze versions**, and 68 predate the field that
  records one. Each item carries a `freeze_digest` over only the fields governing *what a
  model was asked*, so an amendment that could have changed a forecast is distinguishable
  from one that could not.
- **22 pre-registration records** are stored as git notes, each written *before* the
  result it constrains — the statistic, the predicted direction, and how to read every
  outcome including the disconfirming ones.
- **The holdout was spent once.** `map evaluate --split holdout` is refused before anything
  is computed once the spend is recorded. The per-item scores were printed once and never
  persisted; they cannot be recovered, and the app says so rather than showing a gap.
- **Every number on screen carries its provenance** — measured, derived or quoted — and an
  unmarked number fails a test.

---

## Verify it yourself

Not "install a tool" — these are the checks that the claims above are what they say.

**Read the pre-registrations.** GitHub does not show git notes and `git clone` does not
fetch them. Ask for the ref:

```bash
git fetch origin 'refs/notes/*:refs/notes/*'
git log --format='%h %ad %s' --date=iso refs/notes/commits   # 22 appends, in order
git notes show ad71b13                                        # the records themselves
```

The second command carries the evidence for the ordering: it is the history of the notes
ref itself, one commit per append, each timestamped. `git log --show-notes=commits`
displays a note beside its commit but says nothing about **when the note was written**,
which is the whole claim.

`%ad` is the **author** date, and that is deliberate. A rebase on 2026-09-08 rewrote part
of this history and moved several *commit* dates to that day — `9cb1b84` was replayed as
`710879a` with its author date intact — so any ordering read off commit dates would put
work in September that happened earlier. The notes ref was not rebased, and its two dates
agree. Evidence rather than proof, since author dates can be set by hand: what the ref
establishes is that 22 appends exist in a sequence, each recorded before the result it
constrains.

**Run the checks.** All three pass with no inference server and no network.

```bash
uv sync --extra dev
uv run pytest                     # 100% coverage of `mapf`
uv run lint-imports               # the architecture contracts (ADR 0004)
node --test ui/tests/*.test.mjs   # the front end; no build step, no dependencies
```

On a fresh clone most front-end tests **skip**, with the reason — they need an export this
repository does not carry. The summary says so rather than reporting green.

**Check the arithmetic.** [docs/export-contract.md](docs/export-contract.md) states every
file the app reads, field by field. The leakage figure is re-derivable from two files in
the export: `0.03179 − 0.03348 = −0.00169`, and the app shows that subtraction rather than
asserting the result.

**A clone cannot regenerate the data.** `var/` holds the ledger, the run artifacts and the
scoring passes, and none of it is committed — so a clone sees a stated "No export" panel,
not a broken app. `uv run map export --allow-partial` builds what a clone *can*: the frozen
corpus, and five named absences. See [docs/publishing.md](docs/publishing.md).

**Make one yourself.** With the three models loaded on your own machine:

```bash
uv run map serve            # the app and one endpoint, on 127.0.0.1:8765
```

It opens the live-analysis screen. Type a ticker and watch the run happen — the stages
come off the run's own trace, not a timer. This is the one command here that changes the
record rather than reading it.

---

## Documentation

| | |
|---|---|
| [docs/results.md](docs/results.md) | What was measured, in full, with the intervals and the samples |
| [docs/methodology.md](docs/methodology.md) | Corpus construction, scoring rules, baselines |
| [docs/honest-claims.md](docs/honest-claims.md) | What is overstated about projects like this, and the accurate version |
| [docs/setup.md](docs/setup.md) | Requirements, install, model names per backend |
| [docs/cli.md](docs/cli.md) | `map run`, `map prices`, `map runs`, `map export` |
| [docs/export-contract.md](docs/export-contract.md) | Every file the app reads, field by field |
| [docs/publishing.md](docs/publishing.md) | Building a copy to host, and what is third-party |
| [decisions/](decisions/) | 36 ADRs — every non-obvious choice and the alternatives rejected |
| [notebook/](notebook/) | Findings & incidents, the development timeline, current state, the design record |
| [CLAUDE.md](CLAUDE.md) | The working agreement this was built under |

---

## Licence

Copyright © 2026 Kamil Shirinov. All rights reserved.

**Published for review. No licence is granted for reuse, redistribution or derivative
work.** You are welcome to read the code, run the tests and check the claims.

The export served by the app contains data obtained from third parties — SEC EDGAR filings
metadata and Yahoo Finance closes. Those remain subject to their own terms; see
[docs/publishing.md](docs/publishing.md).
