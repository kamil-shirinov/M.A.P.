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

