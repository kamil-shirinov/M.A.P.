# Findings & Incidents

Real bugs and discoveries, in the order they appeared.

Append every new one. Never delete.

---

## 1 · The fabricated gross margin

**Related:** [[0002-constrained-decode-surface]] — what the grammar does and does not guarantee.

**What happened.** On the very first real forecast, Agent 3 wrote *"the high gross margin of 66.3%"*
into a justification. The source document said 46.3%. The analyst had said 46.3%, twice. Agent 3
invented the number.

**Why it matters.** The output was schema-valid, internally consistent, and passed every check in the
system — the grammar, the cross-field validators, all 489 tests. Nothing in Phase 1 could catch it, and
nothing in Phase 1 was ever going to.

**Status.** Not fixed, because it isn't fixable at this layer. Documented in `agents/__init__.py` as a
stated limit *before* it happened, then reproduced deterministically and pinned as a test fixture — a
hallucination you can summon on demand is a rare asset. A numeral-grounding check now warns when a figure
in a justification doesn't appear in the extracted facts. It catches this case, tolerates rounding, and
cannot catch a fabrication written in words.

**The sentence this earns:** *"A schema-valid forecast containing an invented figure passed every
validator I had, on run one. That's why the evaluation layer exists."*

---

## 2 · Nobody owned the magnitudes

**Produced:** [[0014-the-units-experiment]].

**What happened.** The first forecast returned +0.1% / 0.0% / −0.1% over 21 days. The analyst prompt asked
for *qualitative* statements about direction; the structuralist prompt said *don't invent precision that
isn't there*. Neither agent was responsible for producing a number, and the system resolved the
contradiction by converging on zero.

**How it was found.** A 2×2 ablation on the cached narrative — units stated or not, conservatism clause
present or not. Four cells, two minutes, because the expensive analyst call was already cached.

**The result.** Units explained everything; the conservatism clause explained nothing. Both of the confident
hypotheses going in were wrong, in opposite directions.

**Why it's worth telling.** The observation behind the second hypothesis was *true* — the analyst genuinely
stated no magnitudes. The causal story built on it was false. Correct observation, wrong mechanism, and the
experiment was cheaper than the argument.

---

## 3 · The error handler that ate the stack

**Related:** [[0008-inference-timeouts-and-failure-taxonomy]] — the error taxonomy this sits inside.

A 404 was translated into "model not present," and the error message was enriched by calling `list_models()`
to name what *was* loaded. A 404 on `/models` therefore called `list_models()`, which requested `/models`,
which 404'd, which called `list_models()` — until the stack ran out.

**The standing principle it produced:** *error enrichment must never re-enter the path that raised.* Any
call that fetches extra context to improve a message is a potential loop, and it fires precisely when things
are already broken.

---

## 4 · The health check that passed while the server was down

**Related:** [[0001-cache-key-composition]] — the cache this had to bypass.

`map health` was built through the same caching provider as everything else. A cached probe replays its own
earlier answer — so the health check reported on a server it had never contacted.

**The rule:** liveness checks bypass every cache, unconditionally. Anything whose purpose is "is this
reachable right now" cannot be answered from disk.

---

## 5 · The mitigation that contained the failure it mitigated

**Related:** [[0012-price-cache-and-retroactive-adjustment]] — the ADR whose obligation this defeated.

ADR 0012 required Phase 2 to read the manifest and refuse to score across incompatible runs. But the manifest
carried only *its own* `schema_version` — so a harness following that ADR exactly would have read `1.0.0`
while the forecast beside it read `2.0.0`, found it beautifully consistent across every run, and scored a
contaminated corpus.

**Found by** printing the manifest instead of reasoning about it.

**The generalisation:** an obligation on a downstream consumer is worth exactly as much as the field it names
actually meaning what you assumed.

---

## 6 · The `.gitignore` line that would have deleted the test fixtures

A bare `news/` pattern isn't anchored, so it matched *any* directory named `news` at any depth — including
`tests/fixtures/news/`, which the offline test suite depends on. Caught during staging, before the first commit.

Failure mode if missed: CI passes with no fixtures, silently, for weeks.

**Addendum — the same rule failing the other way.** During the vault migration, `.obsidian/workspace.json`
was added to ignore Obsidian's per-session UI state. It silently did nothing: a pattern *containing a slash*
is anchored to the directory holding the `.gitignore`, so it matched `./.obsidian/workspace.json` and never
`M.A.P.-vault/.obsidian/workspace.json`. Fixed with a `**/` prefix.

So the same gitignore rule produced both failure modes: **unanchored matched too much, anchored matched too
little.** Only the first was visible by reading the pattern — the second looked exactly like a working rule
and had to be proven with `git check-ignore -v`.

**The generalisation:** a pattern that silently matches nothing is indistinguishable from one that works,
because both produce no error. Any ignore rule that matters should be verified against a real path rather
than read.

---

## 7 · The test that was testing Plotly

The chart assertions grepped `chart.html` for `cdn.plot.ly` and `tonexty`. Both strings appear as literals
inside the vendored Plotly bundle, so the test passed regardless of what the code did. Now it interrogates the
figure object.

**Class of bug:** a test that passes because of a library's internals rather than your own behaviour. These
survive for years.

---

## 8 · The self-guard that could pass vacuously

**Related:** [[0005-untrusted-text-and-document-identity]] — the invariant the guard protects.

An AST test asserting the sanitiser was constructed in exactly one place included a positive control checking
the function was called *somewhere* in `src/` — which was false, because nothing called it yet. A guard that
can pass while asserting nothing is worse than no guard.

---

## 9 · The justification that was a copy buffer

**Related:** [[0006-justification-before-figures]] — why the justification exists at all.

Every justification truncated mid-word at exactly the character limit — *"exceeding currentcapacity"*, and in
one case a tail containing stray Chinese characters where a 4B broke mid-token. Agent 3 was pasting the
analyst's prose until it hit the ceiling, which quietly defeated the design where justification exists to make
the model reason *before* committing to figures.

Lowering the ceiling from 400 to 240 didn't fix it — it just truncated earlier. The instruction fixed it:
*the justification is yours, not the analyst's.* The ceiling was then restored, with a regression signal in place.

**Lesson:** a model copies because it was told to transcribe, not because it has room. Constraining the budget
attacked the wrong mechanism.

---

## 10 · Fifty percent accuracy that measured nothing

**Related:** [[0017-hedging-measures-metacognition]] — the probe this corrected; [[0018-corpus-band-and-panel-shape]] — the d′ bounds and the pre-committed stopping rule.

The cutoff probe read 50–60% accuracy across every period and it looked like chance-level knowledge. It wasn't.
The model answered **NO to 24 of 24 questions** — a constant responder scores exactly 50% on a balanced yes/no
set. Every earlier reading was response bias, so the recall curve was *invalid*, not merely underpowered.

Fixed by switching to **d′**, which is zero for any constant responder by construction, and by adding an
in-knowledge control: if the instrument can't detect knowledge deep inside training data, the instrument is dead
rather than the knowledge absent. It was dead. A pre-committed stopping rule fired.

---

## 11 · Assumptions that looked like measurements

**Related:** [[0008-inference-timeouts-and-failure-taxonomy]] — where `min_tokens_per_second` is used.

`min_tokens_per_second = 10.0` sat in a config file as though it were a fact. Measured: 16.0. Similarly, the
per-forecast runtime was quoted as 9 minutes long after the horizon and token budget had both changed; measured
cold, it was 500 seconds.

**The category:** a guess written into config acquires the authority of a measurement. Anything that looks like
a constant should say where it came from.

---

## 12 · Two limits that couldn't both be satisfied

**Related:** [[0008-inference-timeouts-and-failure-taxonomy]].

`max_tokens = 12000` and `read_timeout_s = 600` were set independently. At 16 tokens/second the budget needs
~750 seconds, so it was unreachable — a run that genuinely used it would hit the timeout first and report the
wrong failure. Now a startup validator rejects an inconsistent pair.

**Same class as #5:** two numbers that must move together, and didn't.

---

## 13 · The filing arithmetic that mixed item types

**Produced:** [[0018-corpus-band-and-panel-shape]] — the panel re-derived from Item 2.02 counts.

Panel sizing assumed 8–12 8-K filings per company per year. That figure is across *all* item types. The corpus
filters to Item 2.02 — quarterly results — which is four a year at most, roughly 2.9 inside the band. The
proposed 40 × 6 panel required six filings per company that simply don't exist.

Caught before construction; reshaped to 120 × ~3.

---

## 14 · The bootstrap that silently shrank its own sample

**Related:** [[0015-what-the-corpus-can-actually-answer]] — where the suspect result was withheld and later re-derived; [[0018-corpus-band-and-panel-shape]] — the clustering measured with the fix in place.

Block starts were drawn uniformly across the calendar and empty draws discarded, so with 101 of 161 days empty
the resample was far smaller than the sample. The symptom was an *erratic* result that contradicted theory —
29/17/20/16 where it should have been monotone. After fixing the draw to start only on occupied days: 20/18/13/12.

The suspect result had already been marked *"should not be cited"* pending investigation, and was later found
being quoted as corroboration anyway. Both the bug and the citation were removed.

---

## 15 · Look-ahead through the selection door

**Related:** [[0018-corpus-band-and-panel-shape]] — the screen window that now asserts itself.

Two near-misses, both about information entering the study through choices rather than through the model:

- 8-Ks are usually filed after the close. Using that day's close as spot puts the overnight announcement jump
  *inside* the forecast window — crediting the model for a move nobody could have traded.
- The liquidity screen originally had no stated window. Screening on volume from during the forecast period
  would select companies based on the period being forecast.

Both now assert their windows rather than intending them.

---

## 16 · The power analysis that cancelled the experiment

**Produced:** [[0015-what-the-corpus-can-actually-answer]].

Before any corpus was built, a simulation showed the primary question — does the system predict *direction* —
was undetectable at 24% power even for an exceptional forecaster, and would need roughly sixty nights of compute
to reach 80%.

**Cost: zero inference. Saved: roughly forty nights producing a confidence interval spanning zero.**

The question changed to calibration, which is detectable at the corpus already planned, and which has a complete
arc: measure the failure, correct it, measure the correction.


---

## 17 · A log and an instruction are not the same sentence

The vault migration required updating every `docs/` reference in the repo. One occurrence was left alone
deliberately: a dated `STATE.md` entry recording that, back in August, `CLAUDE.md` *"landed in `docs/` and
needs moving back to the root."*

That sentence describes what was true on a particular day. Rewriting the path inside it would have produced
a tidier grep result and a false record — the file's entire value is being an accurate log.

**The principle:** *a log records what was true then; an instruction must be true now.* A migration updates
only the second kind. The two are easy to confuse because they sit in the same file, use the same path
syntax, and both match the grep — the difference is whether the sentence is describing or directing.

The instruction that mattered most in the same pass was in `CLAUDE.md`: it names where ADRs get written, so
leaving it stale would have recreated the old folder next session and split the decision record across two
locations, with nothing failing to signal it.
