# Concepts

Every term used in M.A.P. that a reader might not already know. Each entry says what it
means and **where it appears in this project** — that anchoring is the point. A textbook definition
you can look up; a definition tied to a decision you made is what you'll actually remember.

Add to this the moment something confuses you.

---

## Evaluation and statistics

**Scoring rule** — a formula that grades a probabilistic forecast against what actually happened. A
*proper* scoring rule can't be gamed by lying about your uncertainty. *Used in:* Phase 2 grades every
forecast with these.

**CRPS (Continuous Ranked Probability Score)** — the primary metric. Compares a whole predicted
distribution against a single realised outcome. Lower is better. Reduces to absolute error if your
forecast is a single point, which is how the known-answer test verifies it.

**Brier score** — same idea for a yes/no prediction. Squared difference between the probability you
gave and what happened (1 or 0). *Used for:* directional hit rate — did the price go up?

**Log score** — punishes confidently wrong far more harshly than CRPS. Reported because a model that
assigned near-zero probability to what actually happened deserves to be punished for it.

**Calibration** — whether your stated confidence matches reality. If you say "70% chance" a hundred
times, roughly seventy should happen. *This became the primary question in Phase 2* because
directional skill turned out to be unmeasurable at any affordable sample size ([[0015-what-the-corpus-can-actually-answer]]).

**PIT histogram (Probability Integral Transform)** — a plot showing where realised outcomes fell in
your predicted distributions. Flat means well calibrated. Humped in the middle means your intervals
are too wide. U-shaped means too narrow. This is the plot that tells you *what* is wrong, not just
that something is.

**Statistical power** — the probability your test detects a real effect. 80% is conventional.
*Phase 2's turning point:* the power analysis showed directional skill would be detectable only 24%
of the time even with an exceptional forecaster, which is why the primary question changed. *Decided in:* [[0015-what-the-corpus-can-actually-answer]].

**Effect size** — how big the thing you're looking for is. Small effects need big samples.

**Bootstrap** — estimating uncertainty by resampling your data thousands of times and seeing how much
the answer moves. A **block bootstrap** resamples chunks rather than individual points, to preserve
correlation between nearby observations. *Its empty-block defect and repair:* [[0015-what-the-corpus-can-actually-answer]].

**Design effect** — how much clustering inflates your uncertainty. A design effect of 1.25 means your
344 observations behave like 275 independent ones. *Measured in:* the earnings-season clustering check, [[0018-corpus-band-and-panel-shape]].

**Effective sample size** — your real sample after clustering and overlap are accounted for. Usually
smaller, sometimes dramatically.

**d′ (d-prime)** — from signal detection theory. Measures whether someone can genuinely tell two
things apart, immune to their tendency to always answer one way. *Used in:* the cutoff probe, where
the analyst answered NO to 24 of 24 questions — 50% "accuracy" that measured nothing at all. *See:* [[0017-hedging-measures-metacognition]], [[0018-corpus-band-and-panel-shape]].

**Isotonic regression** — fits a curve that only ever goes up, never down. *Phase 3 uses it* to map
raw model probabilities onto calibrated ones. This is a genuinely trained model.

**GARCH** — a classical model for forecasting volatility from its own recent history. Volatility
clusters: calm follows calm, turbulence follows turbulence. *Used as:* the hard baseline to beat.

**Random walk** — the "no skill" benchmark. Assumes the best guess for tomorrow is today. Surprisingly
hard to beat, which is exactly why it's the benchmark.

---

## Experimental design

**Look-ahead bias** — accidentally using information that wasn't available at the time. Makes a model
look brilliant and is the single most common way backtests lie. *Guarded against in:* the point-in-time
rule, and the liquidity screen ending before the band opens ([[0018-corpus-band-and-panel-shape]]).

**Point-in-time** — using only what was knowable at the moment of the forecast. *In this project:* if
an 8-K is filed after the market opens, the spot price comes from the *next* session's close, so the
overnight announcement jump isn't inside the forecast window.

**Training-cutoff leakage** — the models may already know what happened, because it was in their
training data. Any backtest on pre-cutoff events is contaminated. *Handled by:* splitting the corpus
into clean (post-cutoff) and ambiguous bands and reporting the difference as a measured leakage estimate. *Decided in:* [[0018-corpus-band-and-panel-shape]]; the boundary itself was probed in [[0017-hedging-measures-metacognition]].

**Pre-registration** — fixing your method before you see any results, so you can't tune it toward a
flattering answer. *In this project:* the corpus was committed to git on its own commit before any
inference ran. The commit hash is the proof. *Protocol:* [[0019-corpus-execution-protocol]].

**Development / holdout split** — half the data for tuning, half you look at exactly once. Tuning
against your evaluation set is fitting to the test, and every number afterwards is meaningless.

**Overlapping windows** — consecutive forecasts sharing most of their days aren't independent
observations. *Why the corpus uses non-overlapping dates per company.*

**Common factor** — most stocks move together with the market, so many companies on one day is close
to a single observation. *Why the corpus spreads across both companies and dates.*

**Selection on the dependent variable** — choosing your sample based on the thing you're measuring.
Always invalid. *Why the p90 volatility cap was rejected* — it would have tuned the universe on the
outcome distribution ([[0018-corpus-band-and-panel-shape]]).

**Survivorship bias** — only studying things that still exist, which flatters results. Companies that
went bust don't appear in today's ticker list.

**Data-dependent stopping** — deciding to stop collecting data because of what the data shows. *Why
the two-pass corpus continuation is decided on time alone, without looking at any score* ([[0019-corpus-execution-protocol]]).

---

## Software architecture

**Ports and adapters (hexagonal architecture)** — your core logic depends on *interfaces*, never on
concrete implementations. *In this project:* agents depend on an `LLMProvider` protocol, so they can't
even import `httpx`. Swapping LM Studio for Ollama is a config edit. *Enforced by:* [[0004-import-boundary-enforcement]].

**Dependency inversion** — the reason protocols live in `core` and not in `providers`. High-level code
shouldn't depend on low-level detail; both should depend on the abstraction.

**Protocol (Python typing)** — a structural interface. Anything with the right method shapes satisfies
it, with no inheritance required. mypy checks it at compile time.

**Composition root** — the single place that knows which concrete classes exist and wires them together.
*In this project:* `bootstrap.py`, and nowhere else.

**Import contract / import-linter** — a tool that fails the build if a module imports something it
shouldn't. *Needed because* a plain layered rule would have permitted `agents → providers`, the exact
boundary the design exists to protect. *Decided in:* [[0004-import-boundary-enforcement]].

**ADR (Architecture Decision Record)** — a short document: Context, Options, Decision, Consequences.
Written when a decision is made, never edited afterwards except by amendment. In three years these are
how you reconstruct your own reasoning.

**Constrained decoding / grammar** — forcing a model's output to match a schema by making invalid tokens
literally unreachable during generation. *Why Agent 3 can be a 4B* — the enforcement lives in the sampler,
not the model's intelligence. *Decided in:* [[0002-constrained-decode-surface]].

**Cache key / fingerprint** — a hash of everything that could change an answer: model identity, prompt
text, sampling parameters, decode schema. Same key, same answer, no model call. *Load-bearing here* —
without it a backtest on this hardware is impossible, not merely slow. *Composition decided in:* [[0001-cache-key-composition]].

**Idempotency** — running something twice produces the same result as running it once. *Why the corpus
runner needs a ledger* — otherwise a restart re-runs everything and accumulates duplicates ([[0019-corpus-execution-protocol]]).

**Taint propagation** — tracking untrusted data through a system. *In this project:* text derived from
news stays marked untrusted through the intake and analyst agents, not just at the boundary. *Decided in:* [[0005-untrusted-text-and-document-identity]].

**Prompt injection** — untrusted input containing text that impersonates instructions. *Defended by:*
a sanitiser that normalises unicode, strips control characters, and removes delimiter sequences to a
fixpoint — provably terminating because each pass strictly shortens the input. *Decided in:* [[0009-deterministic-quarantine-delimiters]].

**Fixpoint** — repeating an operation until it stops changing anything. Needed here because removing an
inner delimiter can make two outer fragments adjacent and form a new one.

---

## Finance and data

**Split-adjusted** — historical prices rescaled for stock splits so the series is continuous.
**Dividend-adjusted** additionally adds dividends back. *This project uses split-adjusted* because Stooq
publishes no dividend adjustment, and a fallback that fails the first time it's needed is worse than none. *Decided in:* [[0003-price-adjustment-semantics]]; retroactive re-adjustment is handled by [[0012-price-cache-and-retroactive-adjustment]].

**Ex-dividend date** — the day a stock's price mechanically drops by roughly the dividend. Not a real
loss, but it looks like one in a price series. *Why 21-day windows were rejected* — a third of them
contain one. *See:* [[0013-ex-dividend-windows]], [[0016-five-day-horizon]].

**Realised volatility** — how much a price actually moved, measured after the fact. **Annualised** means
scaled to a yearly figure so different horizons are comparable. AAPL sits around 25–30%.

**Implied volatility** — what options prices say the market *expects*. Not used here.

**GBM (Geometric Brownian Motion)** — the standard model of a random price path: a drift plus scaled
randomness. *Phase 2's Monte Carlo* treats each scenario as one of these and mixes them by probability.

**Monte Carlo** — simulating thousands of random paths and reading the distribution off the results.
Turns three scenarios into an actual probability distribution.

**Fan chart** — the picture of that distribution over time, widening into the future. Only legitimate
*after* the Monte Carlo exists — three lines drawn from three point estimates are not a distribution.

**8-K** — an SEC filing announcing a material event. **Item 2.02** specifically means quarterly results.
Filed roughly four times a year, which is what caps the corpus size ([[0018-corpus-band-and-panel-shape]]).

**Exhibit 99.1** — where the actual earnings press release lives. The 8-K body itself is usually a
two-paragraph cover page pointing at it.

**EDGAR** — the SEC's public filing system. Free, dated, authoritative. Requires a descriptive
User-Agent header or it returns 403 and blocks your IP.

**Accession number** — EDGAR's unique identifier for a filing. *Why the corpus is reproducible* — it's
a list of identifiers plus content hashes, not a folder of scraped text.

**PEAD (Post-Earnings Announcement Drift)** — the documented tendency of prices to keep drifting after
an earnings surprise. Part of the argument for a short horizon, and explicitly *not* claimed as measured
here.

**Dollar volume** — price × shares traded. The liquidity screen uses the *median* rather than the mean,
because one huge day can carry a mean over the floor by itself ([[0018-corpus-band-and-panel-shape]]).

---

## Models and inference

**Inference** — running a trained model forward to get output. **Training** changes the weights.
*Everything in this project is inference;* the model files never change.

**Fine-tuning** — further training on your own data. Not used here, and the reasons are worth knowing:
no labels, far too few examples, and it targets the wrong failure.

**Quantisation** — compressing weights to fewer bits so a model fits in less memory. Q4 means roughly
four bits per weight. **QAT (Quantization-Aware Training)** means the model was trained knowing it would
be compressed, so it loses much less quality — which is why the QAT Gemma build was the right pick.

**GGUF / MLX** — file formats. GGUF runs on llama.cpp, MLX is Apple's own runtime. Both work through the
same OpenAI-compatible API.

**JIT model loading** — the server loads a model on demand and unloads it after. *Essential on 16GB* —
it's how three models coexist when only one fits.

**Context window** — how much text a model can consider at once.

**Reasoning tokens** — output a model generates while thinking, before its actual answer. Gemma 4 produces
thousands per forecast, and they dominate the runtime — about 96% of it.

**Temperature** — randomness in generation. 0 is deterministic. *Agents 1 and 3 run at 0* so their output
is reproducible; the analyst runs at 0.7 because reasoning benefits from variety. *Guarded by:* [[0007-determinism-guard-with-auditable-override]].

**OpenAI-compatible API** — the de facto standard HTTP shape that LM Studio, Ollama, vLLM and others all
implement. Named after who published it first, with no ongoing connection to the company.
