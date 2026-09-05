# Development Timeline

The narrative the ADRs assume you already know. Append to this at the end of every session.

---

## 0 · The original concept, and what was wrong with it

The starting design: three local models in an assembly line — a small one to compress news, a large
one to reason, a small one to emit JSON — feeding "probabilistic forecasting cones" over a price chart.

**What survived:** the three-stage split, local-only inference, the strict output schema.

**What didn't:**

- **No evaluation at all.** An LLM emitting `probability_weight: 0.25` produces a number that looks
  like a probability and has never been checked against anything. The first question any quant desk
  asks is "what's your score against a baseline," and the design had no answer.
- **No forecast horizon in the schema.** `price_modifier_percentage: 4.5` — over what period? The
  output was literally unfalsifiable.
- **Three point estimates are not a cone.** A distribution requires a diffusion process, not three
  lines drawn outward from spot.
- **`qwen3:7b` doesn't exist.** Qwen3 ships 0.6b/1.7b/4b/8b/14b/30b/32b/235b.
- **The "moats" weren't moats.** "Latency optimisation" was actively false — a local 12B is slower
  than a frontier API call. Overclaiming invites the challenge you lose.

**The decision that shaped everything after:** make the evaluation harness the centrepiece, and treat
the forecast as its demo.

---

## 1 · Setting the constraints

**ADRs from this phase:** [[0001-cache-key-composition]] · [[0002-constrained-decode-surface]]

Hardware fixed the architecture more than any preference did. An M1 with 16GB cannot hold three models
at once, so:

- Models load **sequentially**, one resident at a time
- The response **cache became infrastructure, not optimisation** — at ~16 tokens/second, a backtest
  without caching isn't slow, it's impossible
- Agent 3 was **downsized** from 8B to 4B: with constrained decoding the sampler enforces validity, so
  intelligence isn't the binding constraint there

Backend chosen as the **OpenAI-compatible HTTP interface** rather than a specific product, so LM Studio
and Ollama are both a config line. The strings "LM Studio" and "Ollama" are banned from application
code, enforced by a test.

`CLAUDE.md` and `STATE.md` written first, so the repo — not the chat — became the project's memory.

---

## 2 · Phase 1 — building the machine

**ADRs from this phase:** [[0003-price-adjustment-semantics]] · [[0004-import-boundary-enforcement]] · [[0005-untrusted-text-and-document-identity]] · [[0006-justification-before-figures]] · [[0007-determinism-guard-with-auditable-override]] · [[0008-inference-timeouts-and-failure-taxonomy]] · [[0009-deterministic-quarantine-delimiters]] · [[0010-scoped-deprecation-errors]] · [[0011-agent-contracts-and-the-repair-loop]] · [[0012-price-cache-and-retroactive-adjustment]] · [[0013-ex-dividend-windows]]

Nine modules, one at a time, each explained before it was written, each with an ADR for anything
non-obvious.

**core** — every type that crosses a boundary, every protocol, the error hierarchy. The load-bearing
decision: **protocols live in core, not in providers** ([[0004-import-boundary-enforcement]]), so agents depend on interfaces and can't import
`httpx` even transitively. That single choice is what made offline testing free rather than a
monkeypatching exercise.

**settings** — TOML plus environment overlay, environment wins. A placeholder SEC User-Agent that
*refuses to run*, with a test asserting the committed default keeps failing closed so nobody commits a
real contact address.

**providers** — the only module that speaks HTTP to a model. Five distinct error types, because "the
model is loading" and "the server is down" must never look the same. Timeouts split 10s connect / 600s
read, because a localhost socket that won't open in ten seconds isn't coming, but generation legitimately
takes minutes.

**prompts** — the sanitiser, and the central conflict of the module: nonce delimiters would defeat prompt
injection but break the cache permanently. Resolved with fixed delimiters plus normalisation, control-
character stripping, and marker removal to a **fixpoint** ([[0009-deterministic-quarantine-delimiters]]) — provably terminating because each pass
strictly shortens the input.

**agents** — the three roles, plus the repair loop. Taint propagation discovered here: untrusted text
legitimately flows *through* intake and analyst, not just at the boundary.

**data** — SEC symbol index, yfinance with Stooq fallback, parquet cache. The adjustment basis changed
mid-build from split-and-dividend-adjusted to **split-adjusted only** ([[0003-price-adjustment-semantics]]), because Stooq publishes no dividend
adjustment and the fallback would have raised on every call — a fallback that fails exactly when needed.

**pipeline · render · bootstrap · cli** — orchestration, chart, composition root, and the `map` command.
All eight definition-of-done criteria written as named tests.

**Result:** 570 tests, 100% coverage, everything passing with no server and no network. A complete machine
that had never once talked to a real model.

---

## 3 · First contact

**Bears on:** [[0002-constrained-decode-surface]] (the grammar probe returned `enforced`) · [[0001-cache-key-composition]] (fingerprinting degraded to tag)

Three models downloaded (~11.5GB), LM Studio server started with JIT loading and single-model residency.

`map health` answered four open questions at once: **no weight digest exposed** (fingerprinting degraded
honestly to tag), model IDs resolved after the expected alias mismatch, and — the important one — the
grammar probe returned **`enforced`**. The backend genuinely constrains output to the schema, which
validated the whole reason Agent 3 could be small.

Then the first real forecast:

```
bullish   +0.1%    base_case  +0.0%    bearish  -0.1%
```

Over 21 days. A rounding error presented as a bull case.

---

## 4 · The first real debugging cycle

**ADRs from this phase:** [[0014-the-units-experiment]]

Two hypotheses, both confident, **both wrong**:

- *Units mismatch* — the model applied the volatility field's fractional convention to the return field
- *Nobody owns the magnitudes* — the analyst was asked for qualitative statements and the structuralist
  was told not to invent precision, so the numbers converged on zero

A **2×2 ablation** settled it in two minutes, using the cached narrative so it cost almost nothing. Units
explained everything; the conservatism clause explained nothing. The control reproduced the live run
exactly, which is what made the table trustworthy rather than a story about noise.

**The lesson worth keeping:** a correct observation with a wrong mechanism attached. Both parties reasoned
confidently from a true fact to a false conclusion, and the experiment was cheaper than either argument.

Fixed by making the analyst state numeric magnitudes and the structuralist genuinely transcribe them —
restoring the division of labour rather than documenting around its violation. Fractions throughout,
schema bumped to 2.0.0.

---

## 5 · Phase 2 — the design that nearly didn't happen

**ADRs from this phase:** [[0015-what-the-corpus-can-actually-answer]] · [[0016-five-day-horizon]] · [[0017-hedging-measures-metacognition]]

The **power analysis** cost zero inference and changed the entire phase. Directional skill turned out to
be undetectable at any affordable corpus: 24% power at a correlation that would be exceptional for any
equity forecaster, and 80% power would need roughly sixty nights of compute.

**Calibration became the primary question** — not as a retreat, but because it's the only question with a
complete arc: measure the failure, fix it in Phase 3, measure the fix.

Design decisions, each forced by a measurement rather than a preference:

- **SEC 8-K filings** instead of news articles — authoritative timestamps, free, and the corpus becomes a
  list of accession numbers anyone can rebuild
- **Point-in-time alignment** — spot is the close of the first session that *opened* after acceptance, so
  the overnight announcement gap isn't inside the window
- **5-day horizon** instead of 21 — not for statistical reasons (power is horizon-invariant) but because a
  third of 21-day windows contain an ex-dividend date and ADR 0013 requires excluding them
- **Leakage measured, not disclaimed** — clean and ambiguous bands run identically, and the difference *is*
  the contamination estimate

The **cutoff probe** failed on its own terms. Hedge-rate probing turned out to depend on calibrated
metacognition rather than capacity — the 3B over-hedged inside its own training data, the 4B never hedged
at all, only the 12B produced a usable curve. The recall method turned out to be measuring response bias:
24 NO answers out of 24, which reads as 50% accuracy and means nothing. A **pre-committed stopping rule**
fired on the dead branch, and the boundary was placed conservatively on a single signal and labelled as
such.

---

## 6 · The corpus

**ADRs from this phase:** [[0018-corpus-band-and-panel-shape]] · [[0019-corpus-execution-protocol]]

Selection ran mechanically: NYSE and Nasdaq, walked in seeded order, accepting names that clear a
pre-registered median dollar-volume floor measured strictly before the band opens.

**Frozen at commit `36e08a3`** ([[0019-corpus-execution-protocol]] governs how it is executed)**:** 120 tickers, 727 forecasts, dev/holdout 60/60, seed 20260813, with the
price vintage pinned and content hashes for all four prompt templates. Committed on its own, before any
inference ran — so the git history is the pre-registration.

Attrition: 60.7% illiquid, 27.4% no price history, 1.6% too few filings, 10.3% accepted. Liquidity was
the entire binding constraint.

The volatility check fired: median realised volatility came in at 29.6% against the 25% the power figures
assumed, and badly dispersed. Heterogeneity makes over-confidence *easier* to detect and over-dispersion
much harder, so the power table was replaced with the empirical one and the over-dispersion branch stated
as underpowered.

**Next:** the runner, then twelve or so nights of compute, then scoring.

---

## 7 · First contact with real exhibits

**ADRs from this phase:** [[0020-context-window-and-truncation]]

The runner was built, the pre-flight passed, and the clean band started. It halted inside the hour, nine
items in, every failure the same: an 8,192-token context window.

Nothing had ever measured a document against a context. Every test to that point ran on a 470-character
synthetic news file, and a real Item 2.02 exhibit is three orders of magnitude larger — median 31,751
characters, 219,441 at the largest. **The median exhibit did not fit.** The run was going to fail on 54% of
the corpus, and it was not unlucky.

Fixing it properly took four passes, and each one is a lesson about trusting a number rather than measuring
it.

**The memory arithmetic was computed, not estimated.** Llama and Qwen have no sliding-window attention, so
KV cache scales with every layer; Gemma keeps 40 of 48 layers on a 1,024-token window. A 65,536-token intake
would peak at 9.54 GB against a wired limit near 10.6 GB. "Might hold" is the wrong property for twelve
nights, so the answer was a smaller window plus a truncation rule.

**Then the architecture-versus-runtime trap.** The Gemma figure — 0.87 GB at 32k — was derived from what the
architecture *permits*. llama.cpp allocates full-length KV for every layer regardless, about 336 KB/token,
so the real number was 11.0 GB and the server refused to load it. **Wrong by 12.6×, and the error was
believing a capability where a behaviour was needed.**

**So the pre-flight stopped trusting `config` and started measuring the server** — by *bracketing* rather
than by parsing an error message, because two of three agents rejected the probe without naming a number and
because reading one vendor's phrasing is exactly what `CLAUDE.md` §3 forbids.

**And truncation got an enforced invariant rather than a margin.** Head 24,000 tokens, tail 4,000, the
middle elided with a marker — the tail because a guidance table often sits *after* the financial statements,
and guidance is what moves a five-day window.

---

## 8 · The squeeze between the agents

**ADRs from this phase:** [[0021-degeneration-retry]]

Every agent had been checked against its own limits. **The boundary between them belonged to nobody.**

Intake read a 12,500-token document and emitted ~20,000 tokens — it expanded rather than compressed — and
the analyst rejected the resulting prompt. Both agents were individually valid; the pipeline they formed was
not. So the chain got a startup validator: every agent's visible output plus the next one's overhead plus
its generation budget must fit the next one's context.

That capped intake at 2,048 tokens, which raised the obvious question of what happens if it ever hits the
cap. **Nothing, was the answer, and nothing is what had been happening.** A `finish_reason` check went in,
and it fired immediately on two items.

Reading the tails settled what they were. STZ's 18,938-token output was **757 lines of which 22 were
unique** — 97.1% redundant, last new content at line 27, one four-line block repeated 187 times. Not
verbosity. A decoding loop.

**Size does not predict it**: ALLY is a *larger* document and produces 543 clean tokens. So a bigger cap was
never the answer — a cap sized to "what it wants" is meaningless when what it wants is unbounded.

A frequency penalty of 0.3 breaks both loops. It also changes every well-behaved item measured, so it is
applied **only as a retry** after a truncated first attempt. Rescuing two items by perturbing the other 354
is the wrong trade; rescuing them without touching the 354 is not.

---

## 9 · The guard audit

**ADRs from this phase:** [[0022-guard-scope]]

`verify_freeze` refuses to start when the live config has drifted from the frozen record. It had been
passing for weeks. **It compared the model alias and nothing else** — one field of six — so the freeze said
`intake.max_tokens: null` while every run had been configured at 2,048, and the guard whose whole job is
noticing that was looking elsewhere.

An under-checking guard has no failure mode of its own. It just keeps returning green. So every guard,
validator and assertion in `src/` was audited with one question: *what does the name imply, and what does the
code verify?*

**Fifteen gaps, eleven guards sound.** The findings mattered less than their shape, which came in three
kinds: **presence standing in for identity** (a trace guard that checks a file exists, not that it is *this
run's* trace); **a declared number trusted instead of the thing measured**; and **scope narrower than the
sentence** ("this band" with no band filter).

Seven were fixed immediately, including a trace guard that would have passed the incident it was written
for, and a band failure allowance that reset on every resume.

---

## 10 · Two digests, and the guards that would have refused everything

**ADRs from this phase:** [[0026-forecast-digest]] · [[0029-freeze-digest]] · [[0030-code-boundary-adjudication]]

`map evaluate` refused a band produced by more than one commit. The first real scoring pre-flight showed the
band already spanning two, thirty-five items in — **because development continues while a corpus runs, and
it does not stop for twelve nights.**

So the guard would have needed overriding on every run. **A check that must be overridden every time is not
a check.** It is the mirror of a partition that can never fire: one trains you to wave it through, the other
reads as reassurance.

The guard was asking the wrong question. Not *which commit produced this item* but **did anything a forecast
depends on differ**. A hash over the forecast-producing files answers that exactly, and two runs sharing it
are equivalent however many commits separate them.

Backfilling it looked impossible and was not: the digest is a pure function of file contents at a commit,
and every manifest records its commit. **Computing a function of recorded data is not inferring data that
was never recorded** — the distinction that made an earlier timestamp inference wrong and this right.

The same defect turned up one layer up a day later. Amending the freeze to record the execution order took
it from 2.3.0 to 2.4.0 while every field governing what a model is asked stayed byte-identical, and the
freeze check has *no* override. So the frozen record got the same split: ten governing fields, ten recorded
only, each exclusion with a reason that can be stated.

**A version number is never the right equality test.** Both times the guard compared an identifier that
moves for reasons unrelated to what it guards.

---

## 11 · The prefix that would have cost four months

**ADRs from this phase:** [[0027-halt-response]] · [[0028-execution-order]]

Projecting the failure rate forward showed the band halting between item 208 and 312. The power answer was
mild — a halt at 312 costs nothing measurable; one at 208 takes calibration power at the decision-relevant
*k* from 73% to 53%. The thing beside it was not mild.

`plan()` orders items by filing date, so a halt takes **a prefix of the year**. At item 208 that is January
to May 5 — May, June, July and August absent entirely.

`passes.py` already contained the argument for why that is unacceptable, written before any of these
failures. **The protection was designed, reasoned about, and installed on the ambiguous band.** The clean
band, which carries the primary result, ran straight through. The question *"what does an early stop leave?"*
had been asked of the band planned to stop early and never of the one that might stop by accident.

I proposed to record it rather than fix it. That was wrong, and the argument against me was one I already
held: no score exists anywhere, so nothing can be tuned toward a result; applying a documented principle
where it was missed is the opposite of tuning; and execution order cannot reach a forecast, since `as_of`
comes from the filing date, the vintage is pinned, sampling has a fixed seed and the cache is content-keyed.

The remainder now runs in a seeded shuffle. The result is a **hybrid** — 80 contiguous early items plus an
interleaved remainder — stated as that rather than dressed as a clean design.

---

## 12 · Where the run stands

**ADRs from this phase:** [[0023-scoring-adapters]] · [[0024-repeat-rule]] · [[0025-scoring-preflight]]

169 items of the clean band are complete. Scoring is wired end to end and has been exercised on real
artifacts — `map evaluate --check` runs the whole path and prints **no score**, the same boundary the runner
holds between health and result, one layer up.

**Three things are already known about the corpus, before a single number is scored:**

- **Two items are unrescuable.** ALLY's analyst burns its entire 12,000-token reasoning budget and produces
  nothing, twice, against a maximum of 9,487 across every other item. Whether that is a loop or genuinely
  long reasoning **cannot be determined** — the failure raised before the trace was written, so it recorded
  nothing at all. That gap is now closed; the next one will be diagnosable.
- **The band carries three strata.** 135 items adjudicated equivalent, 34 produced from an uncommitted tree
  and therefore unprovable, and 2 superseded by a truncation change and queued for re-running.
- **The failure rate projects past the allowance**, and the response to that is pre-registered rather than
  left to be invented at item 208.

**Next:** the band completes or halts, the analyst runaway gets diagnosed with data that now exists, then
the ambiguous band under [[0019-corpus-execution-protocol]] §8 — clean tree, no commits while it runs.

---

## 13 · The clean band, executed

**ADRs from this phase:** [[0020-context-window-and-truncation]] · [[0028-execution-order]] · [[0030-code-boundary-adjudication]]

**351 of 356 complete, five failures, fidelity 1.0.** It took three runs.

The first halted in its first hour on an 8,192-token context, which is §7. The second ran
for days and ended at 349 with seven failures. The third was not a run so much as a
correction: nine items re-executed after the truncation basis turned out to have moved
underneath the band.

### What made it survivable

Three fixes, each from a failure the band produced rather than one anticipated:

- **The context and the chain.** Windows verified by bracketing the server instead of
  trusting `config`, a truncation rule for the twelve — later eighteen — exhibits that
  did not fit, and a startup validator for the boundary *between* agents, which had
  belonged to nobody until intake emitted 20,000 tokens into a 16,384-token window.
- **The degeneration retry.** Intake looped rather than expanded on two documents, 97%
  and 60% redundant. A frequency penalty applied *only* as a retry rescued them without
  perturbing the other 354.
- **The repeat rule.** "Transient" became a hypothesis the ledger tests: a reason that
  recurs on the same item resolves it, so the band stopped burning fifteen minutes a pass
  on items that could never succeed.

### The seasonal prefix

Mid-run, projecting the failure rate forward showed the band halting between items 208
and 312. The power cost was mild. **The calendar cost was not**: `plan()` orders by filing
date, so a halt takes a *prefix of the year* — at 208, May through August absent
entirely.

`passes.py` already carried the argument against exactly that, written before any of it
happened, and the protection had been installed on the ambiguous band. The clean band —
the one carrying the primary result — ran straight through. The remainder was re-ordered
into a seeded shuffle, leaving a **hybrid**: 80 contiguous early items plus an interleaved
remainder, recorded as that rather than dressed as a clean design.

### The basis that moved underneath it

After the band finished, PRU overflowed its context *after* truncation. The cut is derived
from an assumed characters-per-token ratio, and 3.5 had been justified as "below anything
observed" — on two data points. Measured across 135 completed items: **14% of documents
fall below it**, and a 98,121-character cut needs a true ratio of 3.274 to fit. One
truncated exhibit in twenty was always going to fail.

Correcting the ratio to 3.0 changed what nine items were shown. Six were genuinely stale,
and **three of those were invisible to the freeze digest** because they had fit whole at
3.5 — a content hash records the input that *was* used and cannot represent one that
*would* have been used. The staleness check found them; the digest structurally could not.

The ratio is no longer a safety property: `--check` now measures every cut against the
server's own tokeniser, so too high a ratio produces a visible refusal and too low one
truncates slightly more than needed.

### Final counts

| | |
| --- | --- |
| complete | **351** |
| failed | **5** — ACGL, ALLY, WH (analyst runaway), ATI, JAZZ (intake runaway) |
| transcription fidelity | **1.0** — no unparseable, no divergent |
| truncated exhibits | 9, across four companies |
| degeneration retries | 11 |
| produced from an uncommitted tree | **208** |

**No forecast has been scored.**

---

## 14 · The development half, scored

178 items, 18 date clusters. The holdout is untouched and there is a committed record
proving it ([[0031-holdout-spend]]).

Two things had to be settled before a number could exist. The freeze refusal fired on
two digests, and it turned out to be **counting digest strings when the truncation rule
had been scoped per item** — one record produces two digests by construction, so any
band holding both truncated and untruncated items refuses forever. Computing both
digests for every historical record settled it: the non-truncation digest is
byte-identical across v2.3.0 through v2.6.0. And `--check`'s stale line prints only when
non-empty, so `stale 0` had to be **asserted** rather than read off an absence
([[Findings & Incidents]] #39, fourth instance).

### The result

| | vs earnings-scaled RW | vs GARCH | vs random walk |
| --- | --- | --- | --- |
| CRPS | indistinguishable | indistinguishable | **worse 5.4%** |
| log score | indistinguishable | **worse 11.8%** | **worse 12.8%** |

Brier is **one** comparison, not three: every baseline sets drift to zero, so all three
predict P(up)=0.5 and score exactly 0.25 on every item. Against that coin flip the model
is indistinguishable, at 50.0% accuracy — and the reason is that it barely claims a
direction at all, P(up) spanning 0.369–0.631 around a median of 0.513. Recorded as an
architecture question rather than a scoring one ([[Findings & Incidents]] #46).

### Calibration, after two corrections to my own reading

I first called the PIT tilted, from one tall bin. **Tested, there is no tilt** — mean
0.4893, both cluster-robust intervals covering 0.5 ([[Findings & Incidents]] #43). What
*does* depart is the shape, and only Anderson–Darling sees it: A²=3.044 against 2.492,
while KS reports nothing.

The calibration ratio (0.733) and the PIT disagreed, and **both were right**: the ratio
is dominated by five outcomes carrying 28.5% of the squared returns, while the PIT is
rank-based. The body is calibrated; the tails are thin ([[Findings & Incidents]] #44).
That distinction is why [[0032-calibration-form]] fixes the Phase 3 objective as the log
score rather than the ratio — a scale fitted on 0.733 would widen every forecast by 36%
to accommodate five events.

### The stratum worth watching

The 106 dev items from an uncommitted tree lose to the random walk by 6.0%; the 72 clean
ones are indistinguishable. The intervals overlap heavily and nine clusters is thin, so
this is not evidence of a difference — but it is where the headline result concentrates,
and it sits in the stratum with the weakest provenance.

**Next:** the ambiguous band, under [[0019-corpus-execution-protocol]] §8 — launched from
a clean tree, no commits while it runs.

---

## 15 · Phase 2 closes

The ambiguous band ran from a clean tree at `ad71b13` and closed at **350 of 353
complete, 3 failed, fidelity 1.0**, with **zero items produced from an uncommitted
tree** — the defect that gave the clean band its 208-item stratum did not recur.

It halted once, correctly. Fifteen `exhibit_unreachable` entries across eleven items
were all `[Errno 8]` DNS failures against `www.sec.gov` — no HTTP status, no 403, no
429 — and the five-consecutive rule stopped the band after five, with the cumulative
counter at 6 against an allowance of 8. A local resolver fault cost five items rather
than three hundred, which is the whole argument for having two thresholds instead of
one. Every affected item completed on retry and charged nothing, exactly as
[[0027-halt-response]] said DNS failures should.

EVR 2025-10-29 was retried before any scoring, on protocol symmetry with the clean
band — which ran its repeat rule to completion — and the decision was recorded with
its reasoning before the retry ran. It completed on the second attempt.

### The definition of done, written at the close

Phase 1 had eight criteria written as named tests **before** it started. **Phase 2
never had one.** What follows was assembled at the close from CLAUDE.md §8 and the
ADRs that governed the phase, and it is weaker evidence than Phase 1's for exactly
that reason: a checklist written after the work cannot fail.

**Checked rather than assumed, because the first version of this section asserted it
from a three-directory search.** A `docs/PHASE2_KICKOFF.md` was proposed as the
pre-registered source of these seven criteria. It does not exist and never has: of the
**297 distinct paths ever added on any branch**, none matches `phase` or `kickoff`, and
the `docs/` tree — which existed before the rename to `M.A.P.-vault/` — only ever held
`STATE.md` and `decisions/`.

The contrast is what makes the verdict meaningful rather than pedantic:

| | criteria | committed | before the work? |
| --- | --- | --- | --- |
| Phase 1 | eight, as named tests | `76ded21`, 2026-08-09 — the **initial commit**, alongside `pyproject.toml` | **yes, provably** |
| Phase 2 | seven, below | never | **no** |

So: **genuinely post-hoc.** If a kickoff brief was written and never committed, this
repository cannot show it — and by the standard the project applies everywhere else,
that is the same as not having one. Git history is the pre-registration; an
uncommitted intention is the thing the freeze commits, the ADR ordering and the git
notes all exist to replace.

| # | criterion | met by |
| --- | --- | --- |
| 1 | Monte Carlo over the scenario mixture | `eval/montecarlo.py`; the cone is inverted from the mixture, not sampled, so it cannot disagree with the scenarios |
| 2 | Baselines fitted per item | random walk, GARCH, earnings-scaled random walk — 178 of 178, none defaulted |
| 3 | Proper scoring rules | CRPS, log score, Brier — all three reported against every baseline |
| 4 | A pre-registered panel | [[0018-corpus-band-and-panel-shape]], frozen before any inference, amended only in its own commits |
| 5 | Both bands executed under the protocol | clean 351/356, ambiguous 350/353, every item with a forecast, a trace and a digest |
| 6 | Calibration reported with measured uncertainty | ratio 0.733 [0.637, 0.798]; PIT tilt tested rather than read off a histogram; **no tilt established** |
| 7 | **The leakage estimate** | **clean 0.03189 vs ambiguous 0.03330, difference −0.00141 [−0.00904, +0.00647]** |

### The number the phase exists for

**No measurable contamination.**

The two bands hold the same companies and differ only in when the filings landed —
the clean band after the training cutoff, the ambiguous band across it. A model that
had memorised outcomes would score *better* on the ambiguous band, and that gap would
be the leakage. It scores slightly **worse** there, by about 4%, with an interval from
−0.009 to +0.006 that comfortably contains zero.

Not proof of no leakage; 177 items over 24 date clusters cannot deliver that. But no
sign of it, with the point estimate leaning the way that embarrasses the contamination
hypothesis rather than supporting it. **The headline result — that M.A.P. is
indistinguishable from GARCH on CRPS and worse than the random walk — is not an
artefact of the model having seen these outcomes.**

### What the phase also produced

Two guards that did not exist when it began. `MalformedPriceDataError`, after Yahoo
served five tickers with `open` above `high` and the run died with a fallback provider
configured and never tried. And `RealisedDriftError`, which anchors the outcome bar the
way `SpotDriftError` anchors the spot — **355 pins taken today**, because Phase 3 scores
these same items again and a drifting outcome would otherwise fit a correction against
numbers different from the ones just published.

**Next:** Phase 3 — the calibration correction, pre-registered in
[[0032-calibration-form]] and amended by git note records 3 and 7. The holdout is
unspent.

---

## 16 · Phase 3: the correction generalises, the forecasting does not improve

**Two claims, kept apart all the way through this section, because they are both
true and they point in opposite directions.**

> **Log score convention.** Throughout this project the log score is the *negative*
> log predictive density, so **lower is better**. −1.237 is better than −0.949. The
> convention is stated here because a number that improves by getting smaller is
> exactly the kind of unlabelled direction this vault has recorded five times.

### The fit

`z -> (z - a) / b`, both parameters on the development half, objective the log
score. The objective makes this the normal MLE, so the fit is closed form and there
is no optimiser to misconfigure.

| | value | cluster-robust CI | |
| --- | --- | --- | --- |
| `a` location | **−0.0757** | [−0.4426, +0.1880] | covers 0, exactly as ADR 0032 predicted |
| `b` scale | **1.3305** | [1.2405, 1.4941] | excludes 1 |

`a` fitting to near zero is the result ADR 0032 said it would be, not a wasted
parameter: it was carried so that a location error appearing later could not be a
parameter chosen after seeing the holdout.

### The development success condition FAILED, and a specification gap decided it

Corrected MAD-scale of z: **1.0864 → 0.8165**.

| bootstrap treatment | CI | verdict |
| --- | --- | --- |
| parameters **refitted** per resample | [0.6997, **0.9931**] | **excludes 1.0 → FAIL** |
| parameters held at the estimate | [0.7088, 1.0653] | covers 1.0 |

Record 3 said "judged by the cluster-robust 95% CI from the same moving-block
bootstrap" and **did not say whether `a` and `b` are refitted inside each
resample.** The two readings disagree, and the distance between the failing bound
and 1.0 — **0.0019** — is far smaller than the distance between the readings.

Both estimands are legitimate. The **fixed** reading describes what happens next,
since the holdout applies `a` and `b` without refitting. The **refitted** reading
asks whether the procedure calibrates on a fresh sample, and carries the parameter
uncertainty the fixed one omits. Called **FAIL** on the refitted reading, which is
the treatment that accounts for that uncertainty — but the verdict rests on a
choice the pre-registration left open. Second time this fortnight; see
[[Findings & Incidents]] #49.

### One snapshot, first in the project's history

Mid-phase the development half silently scored 175 instead of 178. Three SCCO items
failed `SpotDriftError` by exactly −1.1858% each. Diagnosed rather than assumed:
SCCO **split 1.012** on 2026-08-11 and the provider applied it about 25 days late.
1/1.012 = 0.988142, matching exactly. It is *not* a dividend — D/P for that date is
0.5497%, less than half — so **[[0003-price-adjustment-semantics]]'s premise holds**:
`Close` is split-adjusted, and a split adjustment is what that basis promises.

The holdout pre-flight then found **zero of its 346 price windows** in the pinned
snapshot, which held only what had been scored by then. So one snapshot was
materialised covering both bands and both splits: **701 of 701 windows at a single
vintage — the first time this corpus has had one.** Every earlier figure rested on
whichever daily fetch was current. The guards worked; what was missing was the
snapshot.

Cost: three SCCO items, reported as a stratum. **Dropping them is conservative
rather than correct** — a return is scale-invariant under a split, so they are
scoreable once the recorded spot is rescaled. The guard cannot tell a split from
genuine drift, which is why it refuses. Split-aware handling is on the Phase 5 list,
deliberately not before the holdout.

Re-derived on the new vintage, **every verdict held**: `a` and `b` moved by 0.003
and 0.0005, the success condition still failed, leakage still spanned zero, the
tails replication stayed PARTIAL and compression still replicated. The commitment to
report all of them whatever they said was recorded before they ran (record 13).

### The holdout was spent, and who decided that

**The pre-registration was silent.** ADR 0032's only sentence about sequencing —
"then reports the holdout once" — is unconditional on its face; record 3 defines
what FAILS means and says nothing about the consequence; ADR 0031 governs how the
holdout is spent, not whether. No conditional statement existed anywhere.

So the decision could not be made by consulting the record, and **Kamil made it
having already seen the failed development fit.** That is recorded rather than
smoothed over. The reasoning: declining would condition the holdout on a
development result, which is precisely the selection the holdout exists to prevent —
a holdout spent only when the fit looks good is a second development set with a
publication filter, and the asymmetry would be invisible in the reported number.

The report was then fixed in git note record 14 — the primary test, seven secondary
measures, and the reading of every outcome including the disconfirming ones —
**before the spend**.

### The result

**173 items, `a` and `b` fixed, no refit.**

| | corrected | uncorrected | difference | |
| --- | --- | --- | --- | --- |
| **log score** *(lower is better)* | **−1.23725** | −0.94947 | **−0.28778 [−0.45255, −0.11117]** | **better** |
| **CRPS** *(lower is better)* | **0.03782** | 0.03873 | **−0.00090 [−0.00178, −0.00012]** | **better** |

Both intervals exclude zero in favour of the corrected forecast, on 173 items over
22 clusters that had never been examined. **The correction generalises.**

Secondary measures:

| | before | after |
| --- | --- | --- |
| calibration ratio | 0.5922 [0.4937, 0.7489] | 0.7879 [0.6568, 0.9964] |
| MAD-scale of z | 1.3795 [1.1589, 1.6649] | **1.0368 [0.8711, 1.2514]** — covers 1.0 |
| tail ratio | 1.1747 | 1.1833 |
| PIT tilt | 0.5410 | 0.5512 — not established |
| Anderson–Darling | 12.204 | 4.145 *(cluster-robust 5% point 5.084)* |
| \|z\|>2.5 | 16 (9 blk) | 9 (7 blk) *(expectation 2.15)* |
| \|z\|>3.0 | 11 (8 blk) | 3 (3 blk) *(expectation 0.47)* |

Strata: **dirty-tree 102 of 173**, truncated 2, degeneration retries 4,
`SpotDriftError` exclusions 0.

### The holdout did NOT refute the development failure

The obvious reading — development failed, holdout passed, so the failure was a
fluke — **does not survive testing.** The two halves are not distinguishable from
each other:

| statistic | development | holdout | difference | |
| --- | --- | --- | --- | --- |
| uncorrected calibration ratio | [0.6380, 0.8030] | [0.4967, 0.7483] | +0.0978 [−0.0584, +0.2485] | **not distinguishable** |
| uncorrected MAD-scale | [0.9430, 1.4173] | [1.1589, 1.6649] | −0.1645 [−0.5779, +0.1349] | **not distinguishable** |
| **corrected MAD-scale** | [0.7088, 1.0653] | [0.8711, 1.2514] | −0.1236 [−0.4343, +0.1014] | **not distinguishable** |

The intervals overlap on 54–67% of the narrower one, and every difference covers
zero. **The FAIL and the PASS are two marginal calls landing either side of 1.0 in
samples that cannot be told apart** — one excluding 1.0 by 0.0019, the other
covering it. Neither refutes the other, and reporting the holdout as having
vindicated the correction's calibration would be reading a coin flip as a verdict.
See [[Findings & Incidents]] #49.

### What did and did not improve

**The calibration correction generalises out of sample.** That is established: both
primary measures, both intervals excluding zero, on a sample never examined.

**The forecasting did not improve.** Corrected, the system now beats the
earnings-scaled random walk on CRPS — a change from indistinguishable — and still
**loses to GARCH and to the plain random walk on both CRPS and the log score**, as
it did uncorrected. A better-calibrated statement of the same information is worth
having and is not the same as a better forecast.

**Next:** the three-agent ablation ([[Findings & Incidents]] #46), which has a
specific prediction to test rather than being a loose end. The holdout is spent and
cannot be reused.

