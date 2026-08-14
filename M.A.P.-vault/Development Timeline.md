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
