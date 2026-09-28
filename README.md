# M.A.P. — Market's Agentic Projections

Three local open-weight models read an earnings filing and produce a probabilistic
five-day price forecast. The forecast is then **scored against what actually happened**,
on a corpus frozen and committed before any forecast on it was made.

**[→ Open the app](PLACEHOLDER_URL)** — 779 runs, 175 scored items, every figure marked
with where it came from.

> **Published for review. No licence is granted for reuse.**
> Copyright © 2026 Kamil Shirinov. You are welcome to read this and check it.
> See [Licence](#licence).

---

## What it found

**It does not beat a plain random walk or GARCH on the development companies.** That is
the headline result and it is not buried.

| On 175 clean-band development items | M.A.P. | random walk | GARCH |
|---|---|---|---|
| CRPS *(lower is better)* | 0.03179 | 0.03016 | 0.03105 |
| Log score *(lower is better)* | −1.3786 | −1.5826 | −1.5659 |
| Direction | 87 of 175 — **49.7%** | a coin | a coin |

Against the random walk the CRPS gap is **+0.00163 [+0.00071, +0.00278]** and the log
score gap **+0.2040 [+0.08004, +0.36396]** — both intervals exclude zero, both in the
wrong direction. Against GARCH, CRPS is indistinguishable and the log score is worse.
Against a random walk widened for earnings days its point estimate is better — CRPS
−0.00100 — but the interval is [−0.00222, +0.00111] and spans zero, so that difference is
not established either.

Four more things were measured, and they are the reason the project exists.

**1. The stated uncertainty was too narrow, and that was fixable.**
The forecasts claimed intervals about 27% tighter than the outcomes justified
(calibration ratio 0.733, where 1.0 is calibrated). A two-parameter correction — shift
and widen — was fitted on half the corpus, pre-registered, and then **spent once** on
the other half, which had never been examined:

**The pre-registered success condition failed first.** It asked that the corrected
MAD-scale of `z` be consistent with 1.0 on development. Refitting the parameters inside
each bootstrap resample — the reading that carries the parameter uncertainty — gives
**[0.6997, 0.9931]**, which excludes 1.0 and so **fails, by 0.0069**. Held fixed it
passes. The pre-registration named a threshold without naming its estimator, so both
readings were legitimate; it was called FAIL on the stricter one, and the gap in the
pre-registration is recorded as a gap. The rule since: *a threshold is not a
pre-registration unless the estimator is also pre-registered.*

**Nothing said whether a failed condition still spends the holdout**, so that decision
could not be made from the record. **Kamil made it, having already seen the failed
fit**, and it is recorded as his judgement in git note record 12 rather than smoothed
over. The reasoning: declining would condition the holdout on a development result,
which is exactly the selection a holdout exists to prevent — one spent only when the fit
looks good is a second development set with a publication filter.

So the holdout was spent with the condition already failed:

| On the 173 holdout items | corrected | uncorrected | difference |
|---|---|---|---|
| Log score | **−1.23725** | −0.94947 | **−0.28778 [−0.45255, −0.11117]** |
| CRPS | **0.03782** | 0.03873 | **−0.00090 [−0.00178, −0.00012]** |

Both intervals exclude zero. **The correction generalises** — it works on data it was
not fitted on, and it was not spent on a fit that had passed. The holdout is now spent
and cannot be spent again. No claim is made that this refutes the development failure:
the two halves are not distinguishable from each other.

**2. No measurable training-cutoff leakage.**
The corpus is split into filings from *after* the models' training cutoff (clean) and
*before* it (ambiguous). If the models were remembering rather than forecasting, the
ambiguous half would score better. It does not: **−0.00169 [−0.0093, +0.0060]** on mean
CRPS. The two halves are not distinguishable.

**3. The tails are heavy — and that replication was only partial.**
Outcomes land beyond 2.5 standard deviations about five times more often than a normal
predicts, and the two normal-tailed baselines scored on the same outcomes do not show it,
so the excess is M.A.P.'s rather than the market's. It was pre-registered as a test on a
second band before any of that band was scored, requiring **both** the counts and a tail
ratio whose interval excludes 1.0.

**The counts replicated and the ratio did not.** On the ambiguous band, 11 items exceed
2.5 (about 5× expectation) and 8 exceed 3.0 (about 17×, against a predicted 10–15×),
spread over six blocks. The ratio did not clear its bar, so the verdict was recorded as
**PARTIAL** and stayed partial when the whole corpus was re-derived on one price vintage.
Adopting a Student-t predictive distribution was triggered on full replication, so
**it was not adopted** — on the trigger, not on a later judgement.

**4. One finding did replicate cleanly, out of sample: volatility compression.**
M.A.P. states too narrow a *range* of volatilities across companies — roughly right in
the middle of the cross-section, far too narrow on the names that actually move. On
development, the slope of log σ(M.A.P.) on log σ(random walk) is **0.3166 [0.2609,
0.3811]**, far below 1. This was pre-registered on 2026-09-02 while the ambiguous band
was still running and before any ambiguous item was scored, and it **replicated against
both baselines**. It is the candidate explanation for the heavy tails and the narrow
calibration ratio at once: too-small sigma on the names that move produces the
exceedances, and those few items dominate the ratio.

**What this is not.** Not trading advice, not a signal, not a product. No order
execution, no position sizing, no broker integration. It is an engineering and
methodology exercise whose result happens to be negative.

---

## Why the negative result is the point

A forecasting system that cannot be scored is not a forecasting system. Most of the work
here is in making the claims falsifiable and then letting them fail:

- **The corpus was frozen and committed before any forecast on it was made** — 120
  tickers and 727 forecasts at commit `36e08a3`, 2026-08-14, whose message is *"FREEZE
  THE CORPUS -- pre-registration artifact"*. The commit order is the pre-registration.
  *Not* "before any inference ran": the pipeline was being built and exercised for weeks
  beforehand, and `runs/266aa3ba…` is an AAPL run dated 2026-08-11. Those are development
  runs on no corpus, they carry a pre-manifest schema, and none is in the journal or any
  scored population — but "before any inference" would be false, so it is not said.
- **Membership was amended once, the next day, and still before any forecast existed.**
  A pre-flight fetch found **30 of 727 items had no usable Exhibit 99.1** — over the 2%
  failure allowance, so the run would have halted on night one. `BRK-A` was dropped as a
  duplicate CIK with `BRK-B` (one company, one 8-K, one exhibit, counted twice — three
  duplicate exhibit hashes made it visible) and `GEN` for carrying no EX-99.1 on any
  filing; `CG` and `WULF` replaced them, taken from the next names in the seeded
  ordering. **727 forecasts → 709.**
  This is the *pre-registered replacement rule being applied, not a new rule*: whether a
  company attaches its release as EX-99.1 is a deterministic property of how it files,
  identical every quarter and in both bands. It was a criterion that should have been
  screened at selection, and discovering it late made it a missed criterion rather than a
  new one. The reasoning, the counts and the before/after table are in
  [ADR 0018](decisions/0018-corpus-band-and-panel-shape.md), which states plainly: *"The
  amendment precedes all inference. No forecast has been produced, so no result could
  have influenced which tickers were dropped."* Commit `36e08a3` was kept rather than
  rewritten, so the pair shows what was known when.
- **Later amendments changed how items were run, not which items.** The 779 runs span
  **four freeze versions**, and 68 predate the field that records one. Each item carries a
  `freeze_digest` over only the fields governing *what a model was asked*, so you can tell
  an amendment that could have changed a forecast from one that could not: the
  execution-order change (2.3.0 → 2.4.0) hashes **identically**, and the truncation change
  (2.4.0 → 2.5.0) differs for exactly the two items whose documents were cut.
- **22 pre-registration records** are stored as git notes, each written *before* the
  result it constrains — fixing the statistic, the predicted direction, and how to read
  every outcome including the disconfirming ones. You can fetch and read them.
- **The holdout was spent once.** `map evaluate --split holdout` is refused before
  anything is computed once the spend is recorded. The per-item scores were printed once
  and never persisted; they cannot be recovered, and the app says so rather than showing
  a gap.
- **Every number on screen carries its provenance** — measured, derived or quoted — and
  an unmarked number fails a test.

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

The second command is the one that proves the ordering: it is the history of the notes
ref itself, one commit per append, each timestamped. `git log --show-notes=commits`
displays a note beside its commit but says nothing about **when the note was written**,
which is the whole claim.

**Run the test suites.** Both pass with no inference server and no network.

```bash
uv sync --extra dev
uv run pytest                     # 1,616 tests, 100% coverage of `mapf`
node --test ui/tests/*.test.mjs   # the front end; no build step, no dependencies
```

On a fresh clone most front-end tests **skip**, with the reason — they need an export
this repository does not carry. The summary says so rather than reporting green.

**Check the arithmetic.** [docs/export-contract.md](docs/export-contract.md) states every
file the app reads, field by field. The leakage figure above is re-derivable from two
files in the export: `0.03179 − 0.03348 = −0.00169`, and the app shows that subtraction
rather than asserting the result.

**A clone cannot regenerate the data.** `var/` holds the ledger, the run artifacts and
the scoring passes, and none of it is committed — so a clone sees a stated "No export"
panel, not a broken app. `uv run map export --allow-partial` builds what a clone *can*:
the frozen corpus, and five named absences. See [docs/publishing.md](docs/publishing.md).

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

The scenarios become a Monte Carlo distribution; that is scored against the realised
close with CRPS, log score and Brier, against three baselines — a random walk, a GARCH
fit, and a random walk widened for earnings days.

**All inference is local.** No data goes to a third-party model provider. This is *not*
"100% offline": prices come from Yahoo Finance and filings from SEC EDGAR, and those
parties see what is asked of them.

---

## Documentation

| | |
|---|---|
| [docs/results.md](docs/results.md) | What was measured, in full, with the intervals |
| [docs/methodology.md](docs/methodology.md) | Corpus construction, scoring rules, baselines |
| [docs/honest-claims.md](docs/honest-claims.md) | What is overstated about projects like this, and the accurate version |
| [docs/setup.md](docs/setup.md) | Requirements, install, model names per backend |
| [docs/cli.md](docs/cli.md) | `map run`, `map prices`, `map runs`, `map export` |
| [docs/export-contract.md](docs/export-contract.md) | Every file the app reads, field by field |
| [docs/publishing.md](docs/publishing.md) | Building a copy to host, and what is third-party |
| [decisions/](decisions/) | 35 ADRs — every non-obvious choice and the alternatives rejected |
| [notebook/](notebook/) | Findings & incidents, the development timeline, current state, the design record |
| [CLAUDE.md](CLAUDE.md) | The working agreement this was built under |

---

## Licence

Copyright © 2026 Kamil Shirinov. All rights reserved.

**Published for review. No licence is granted for reuse, redistribution or derivative
work.** You are welcome to read the code, run the tests and check the claims.

The export served by the app contains data obtained from third parties — SEC EDGAR
filings metadata and Yahoo Finance closes. Those remain subject to their own terms;
see [docs/publishing.md](docs/publishing.md).
