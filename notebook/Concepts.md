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

**Design effect** — the factor by which clustering inflates a variance estimate. Item 2.02 filings land in
reporting season, so many forecasts share days and overlapping windows; treating them as independent would
give an interval far too narrow. *Handled by:* a moving-block bootstrap over calendar time rather than an
i.i.d. one over items.

**Stratum** — a subset of the sample that has to be reported apart because something about how it was
produced differs. The clean band has three: 135 items adjudicated equivalent, 34 produced from an
uncommitted tree, and 2 superseded by a truncation change. *The point of naming one* is that pooling it
silently is the failure; reporting it is not.

**Code boundary adjudication** — deciding, for each pair of adjacent code states in a corpus, whether the
difference could have changed what a model was asked. Done **before any score exists**, because at scoring
time the judgement stands between you and a fortnight's work and *"these files look like plumbing"* becomes
much easier to believe ([[0030-code-boundary-adjudication]]). *"Cannot tell" is a permitted answer* — with
only two options, the verdict gets forced.

**Repeat rule** — "transient" is a hypothesis about an item, and the ledger already holds the evidence to
test it. A failure reason that recurs on the same item stops being transient and the item is resolved
([[0024-repeat-rule]]). *Excludes* shared-infrastructure failures: five items failed together when DNS
dropped, and what they had in common was the afternoon, not the filing.

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
Written when a decision is made, never edited afterwards except by amendment. Years later these are
how the reasoning is reconstructed.

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

**Forecast digest** — a hash over every file that can produce a forecast, recorded beside the commit
([[0026-forecast-digest]]). The commit is the wrong equality test: a twelve-night corpus spans every commit
made while it runs, so comparing commits gives a guard that must be overridden every time — which is not a
guard. *Two runs sharing a digest are forecast-equivalent however many commits separate them.*

**Freeze digest** — the same idea for the frozen corpus record ([[0029-freeze-digest]]). Ten fields govern
what an item was asked (models, prompts, contexts, truncation, the retry, the horizon, the price vintage,
the exhibit hashes, membership, KV cache); the rest are recorded and excluded. *Why it was needed:* an
amendment that only wrote down the execution order bumped the version while changing nothing a model sees.

**Dirty tree** — a working directory with uncommitted changes. A run launched from one records no forecast
digest, because the commit does not describe the files that executed, so its items can never be shown
equivalent to anything. *34 items of the clean band are in that position*, which is why the runner now
refuses to start on one ([[0019-corpus-execution-protocol]] §8).

**Bracketing probe** — measuring a server's real context window by sending one prompt just under the
configured size (must be accepted) and one well over (must be rejected), rather than parsing the number out
of an error message ([[0020-context-window-and-truncation]]). *Works on any backend*, including one that
says nothing at all — and reading one vendor's phrasing is what `CLAUDE.md` §3 forbids.

**Canary** — a request so small that no configured window could refuse it, sent before the bracket. If even
that is rejected the server is busy or unwell and the window was never measured. *Without it*, running the
pre-flight beside a live corpus reported every agent's context as TOO SMALL — on the exact windows the run
was succeeding with.

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

**Chars-per-token ratio** — how many characters of text one token holds, used to estimate a document's size
before sending it. Set at 3.5 on two observations and described as "below anything observed"; measured
across 135 completed items the real distribution is min 3.017, median 3.887, and **14% of documents fall
below 3.5**. *One truncated exhibit in twenty was always going to overflow*, and one did
([[0020-context-window-and-truncation]]). Now 3.0, and — more importantly — **no longer a safety property**:
the pre-flight measures every cut against the server's own tokeniser, so too high a ratio gives a visible
refusal and too low one truncates slightly more than needed.

**Degeneration** — a model looping instead of reasoning. Distinguished from genuine verbosity by redundancy:
one intake output ran to 757 lines of which **22 were unique**, with the last new content at line 27. *Size
does not predict it* — a larger document produced 543 clean tokens.

**Degeneration retry** — one re-run of a looping call under a frequency penalty, applied only after a first
attempt was cut off ([[0021-degeneration-retry]]). *Never as a default*, because the same penalty changes
every well-behaved item: rescuing two items by perturbing the other 354 is the wrong trade.

**Reasoning tokens** — tokens a reasoning model spends thinking before it writes an answer, reported apart
from the visible output. A model can burn its whole budget here and emit nothing, which **looks exactly like
a refusal** and is not. *The trap:* the reasoning text itself was never recorded, so a runaway could be
counted and never read.

**Characters-per-token ratio** — see *Models and inference*. Worth repeating here because
it is the parameter that moved: it converts a document's length into an estimate of what
it will cost a model, and a **refusal gate must sit at or below the floor of what it
gates**, not near the middle of it.

**Positive control** — a case where a measure *must* separate, run to prove the measure
can separate at all. A null result from a measure with no dynamic range says nothing, and
looks identical to a null from a measure that works. *Used in:* the redundancy
falsification, where the corpus's largest exhibit was measured against its smallest before
the null was believed.

**Screen versus comparison** — a design that can establish something is *present* is not
automatically one that can establish two things *differ*. Five draws per arm surface a
per-draw probability of 0.3 with 83% chance, but 2-of-5 against 0-of-5 is p = 0.44 and
indistinguishable from chance. *Stated in advance* so a partial result is not read as a
verdict.

**Natural experiment** — two cases that differ in the thing you care about and match on
everything else, found rather than constructed. *The corpus has one:* ACGL 2026-02-09
failed and ACGL 2026-04-28 passed, **35 characters apart**, same company, same filing
type, adjacent quarters.

**Supersession record** — the append-only way to invalidate an entry: a new line saying
*this item was invalidated by amendment X*, rather than deleting the old one. *Not yet
built* — the current mechanism deletes lines, which erased one item's genuine failure
history ([[Findings & Incidents]] #39).


**Spend record** — the append-only proof that a one-shot resource was used once. Scoring the holdout
appends a line — date, commit, forecast digest, freeze version, and which calibration artifact was in
place — and any later holdout run refuses against it ([[0031-holdout-spend]]). *Committed, deliberately:*
the git history is then the proof, in the way the frozen-corpus commit is the proof the corpus was
pre-registered. An absence is checkable by anyone; a promise is checkable by no one.

**Spent before shown** — the spend is recorded *before* the first number is printed, because a holdout is
spent when it is **seen**, and a crash between computing and displaying would otherwise leave it looking
untouched. A repeat could then be justified as *"the last one didn't finish"* — true, and still a second
look. *Erring the other way* burns a holdout nobody read; that is the cheaper error.

**Required with no default** — an option deliberately left without one, so the dangerous choice cannot be
made by forgetting. `--split` has no default because a default is a decision made by whoever omits the
flag, and the holdout must not be scoreable by omission.

**Multiplicity in a picture** — a histogram with ten bins is ten implicit tests, and one will sit outside
its 90% range by construction. Reading a shape off one is not a free look at the data ([[Findings &
Incidents]] #43). *The fix is not to look harder* but to state the statistic before looking.

**Tilt versus shape** — two different departures from a uniform PIT, needing two different instruments.
The mean against 0.5 finds a *tilt* (biased one way); Kolmogorov–Smirnov and Anderson–Darling find a
*shape*. A symmetric U has a mean of exactly 0.5, so the tilt test is silent on the most common
miscalibration there is.

**KS versus Anderson–Darling** — KS is driven by the largest gap between the empirical and uniform CDFs,
which for a symmetric departure sits in the middle where the curves cross anyway. A² carries a 1/(u(1−u))
weight and is built for the ends. *On the development half they disagree* — KS 0.0698 (p=0.345), A² 2.838
against 2.492 — and the disagreement locates the problem in the tails.

**Aggregation is not diagnosis** — the calibration ratio is a quotient of root-mean-squares and is
dominated by the largest outcomes; the PIT is rank-based and barely notices them. 0.733 was a true fact
that supported a false conclusion, caught only because both were reported side by side ([[Findings &
Incidents]] #44).

**A parameter carried on purpose** — `a`, the location shift in [[0032-calibration-form]], is not motivated
by the development evidence and is in the form anyway. Leaving it out and adding it later, after the
holdout showed a location error, would be a parameter chosen on the holdout. *Fitting to near zero is a
result*, not a wasted degree of freedom.

**Uninformative null** — a null result from a design that could not have produced anything else. The corpus
is entirely EX-99.1 issuer text, so a test for issuer-promotion skew has nothing to be *relative to*
([[Findings & Incidents]] #45). Distinct from a null that constrains.

**Declining to commit** — a forecaster whose directional probabilities cluster at 0.5 cannot be right or
wrong about direction, so a Brier score against a coin flip restates the span rather than measuring skill
([[Findings & Incidents]] #46). *An architecture question*, which is what gives the three-agent ablation a
specific prediction to test.

**Value provenance** — a marker travelling with a stored number saying whether it was measured, derived
from measured inputs, or fabricated, with the weakest input winning so it cannot be laundered through
arithmetic ([[Findings & Incidents]] #48). *The pipeline has provenance for runs and none for values:* a
float in a JSONL file is a float, and `139.34` from a test helper is indistinguishable from `94.70` from
Yahoo. Named gap, candidate design already running in the front end.

**Uncommitted pre-registration** — an intention written in advance and never committed, which this project
treats as equivalent to no pre-registration at all. Git history is the evidence; a brief that cannot be
shown is the thing the freeze commits and the git notes exist to replace ([[Development Timeline]] §15).

**Marginal calls on indistinguishable samples** — two verdicts landing either side of a threshold in
samples a test cannot separate. Neither is evidence about the other, and treating one as commentary on
the other reads a coin flip as a verdict ([[Findings & Incidents]] #49). *The defence is asking whether
the samples differ* before letting one interpret the other.

**Estimator-completeness of a threshold** — a pre-registered condition is only complete if the estimator
is fixed too: the resampling scheme, what is refitted inside it, and the null. Naming the statistic, the
level and the direction leaves a degree of freedom that gets decided at reading time, with the answer
visible. *Cost twice in one fortnight* — ADR 0032's iid A² point, and record 3's unspecified refit.

**Frozen vintage** — a price snapshot pinned by date and READ-ONLY, so a missing window refuses rather
than fetching. Without the read-only half the pin is cosmetic: a miss stores today's series under the
pinned name, which is the calendar-keyed cache wearing a fixed label. *701 of 701 windows at one vintage
is the first complete single-vintage snapshot this corpus has had.*

**Conservative versus correct** — a guard that refuses a case it could in principle handle. The three
SCCO items are scoreable once the recorded spot is rescaled by the split factor, because a return is
scale-invariant under a split; `SpotDriftError` refuses because it cannot tell a split from genuine
drift. *Recording the distinction is what keeps a known limitation from hardening into a believed one.*

**Narrating versus stating** — a document that *narrates an event* records what was true at that event; a
document that *states current status* states current truth. The Timeline's earlier sections and dated
Findings entries keep their original figures; STATE.md and the closing sections carry the present ones.
*ADRs are the strongest case of narrating:* an ADR overwritten to match later data destroys the only
evidence that the reasoning fitted the evidence available when the decision was made, so ADRs are
**amended, never edited**.

**Superseded marker** — one greppable string, `[superseded YYYY-MM-DD -> target]`, rather than prose, so
every stale figure in the vault can be found in a single search. Prose annotations cannot be enumerated,
which means nobody can answer "what else is out of date" without re-reading everything.

**Amending a pre-registration** — a pre-registration may be amended to make a caveat *stronger* before the
result exists; it may never be edited to look as though the error was not made. **A pre-registration
amended to look as though the error never happened is worthless** — its whole value is being a record of
what was believed in advance, and a record that silently improves itself is not one. *The worked example
is record 16 contradicting record 15:* record 15 called the no-analyst prompt change "minimal", building
it showed 11 of 25 lines change, and record 16 says so while leaving the original sentence standing.

**Re-purposing a gate versus a measurement** — a gate has a decision attached and can be moved to change
an outcome, so re-purposing one after the fact is a researcher degree of freedom. A variance measurement
of an already-stated property has nothing to move: no hypothesis, no threshold, no branch. *The
ablation's 60-item control was re-purposed from gating A−B to measuring whole-pipeline re-derivation
variance* (git note record 20), and the distinction is why that is legitimate where re-purposing a test
would not have been. **The test of whether re-purposing is safe is whether any outcome could be changed
by it.**
