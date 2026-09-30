# Findings & Incidents

Real bugs and discoveries, in the order they appeared. **This is the hardest part of the record to
reconstruct afterwards** — working code survives on its own, while what a system got wrong and how it
was found out survives only if it is written down at the time.

Append every new one. Never delete.

---

## The lesson that generalises furthest

**A bug that crashes gets investigated. A bug that produces a plausible result gets published.**

Most entries below were found because something broke loudly. The expensive ones are the entries where
nothing broke at all:

- a schema-valid forecast containing an invented gross margin, which passed every validator (#1)
- forecasts converging on ±0.1% because no agent owned the magnitudes — a rounding error presented as a
  bull case (#2)
- a manifest reporting `1.0.0` beside a forecast reading `2.0.0`, perfectly consistent across every run
  and consistently wrong (#5)
- a chart test passing on strings inside the vendored Plotly bundle rather than on anything the code did (#7)
- 50% recall accuracy that was a model answering NO to everything (#10)
- an exhibit lookup matching a field that holds an icon filename, failing for **100% of filings** — a
  number that reads as a finding about the corpus rather than as a defect (#18)
- a KV-cache figure computed from what the architecture permits, reported as what the runtime does,
  wrong by 12.6× (#20)
- an agent that expanded a document instead of compressing it, uncapped, because each agent was
  checked against its own limits and the boundary between them belonged to nobody (#21)

---

## The third lesson: a true sentence can still mislead

**Two correct numbers in one sentence can invite a wrong reading, and review does not catch it, because
every number checks out.**

ADR 0018 says: *"The primary result is calibration on the clean band, at 120 × ~2.87 ≈ 344 forecasts.
Power: 100% at k=0.2, 93–98% at k=0.5, ~32% at k=0.8."* Both figures are right. The 344 is the corpus; the
power belongs to the **reportable ~90** left after the holdout and post-cutoff splits. Read in one pass it
says the power belongs to the 344 — and `power.py`'s own docstring names that exact confusion as the thing
it exists to prevent: *"sizing on the full corpus and reporting on a quarter of it."*

It survived because there is nothing to catch. No number is wrong, no claim is false, and a reviewer
checking facts finds only facts. What is wrong is the **adjacency** — a sample size and a power figure in
one sentence assert a relationship between themselves that neither states.

The repair is not more precision. It is to put the number the reader will quote next to the thing it is
about: *"power is computed on the reportable subset (~90 of the 344)."*

**The question to ask of a summary sentence:** *if someone quotes this from memory, what will they say?* If
the answer differs from what it means, the sentence is the defect, not the reader.

---

## The second lesson, which took three instances to see

**A test that would pass under both the bug and the correct behaviour is not a test.**

It is worse than no test, because it occupies the place where a real one would go and reports success
from it. Three separate cases, none related to the others, all found by accident:

| | The assertion | Why it could not fail |
| --- | --- | --- |
| **#7** | `chart.html` contains `cdn.plot.ly` and `tonexty` | Both strings are literals inside the vendored Plotly bundle. The file contained them whatever the code did. |
| **#8** | the sanitiser is called *somewhere* in `src/` — a positive control | It was false, because nothing called it yet. The control that existed to prove the scan worked was itself asserting nothing. |
| **#26** | the earnings baseline's CRPS "looks reasonable" | CRPS is dominated by the size of the realised move, so a leak and a large move are indistinguishable in it. |

The repair is the same in all three, and it is not "assert harder". It is to find an input pair the bug
and the correct behaviour **must** answer differently, and assert on the difference:

> Identical history through the window, a different one afterwards, and every score **bit-identical**.

That statement is false under a leak and true otherwise, with no threshold to tune and no magnitude to
eyeball. The same shape retro-fixes the other two: interrogate the figure object rather than the rendered
file; make the positive control assert a construction site that provably exists.

**The question to ask of a new test:** *what would this print if the thing it guards were broken?* If the
answer is "the same thing", it is decoration.

A fourth arrived while this very entry was being written, in the test for it. An assertion read
`"leakage" not in result.output` — and pytest's `tmp_path` carries the test's own name, which contains the
word *leakage*, so the substring matched the **directory path** rather than anything the code printed.
Finding #7 exactly, in a fixture, twenty minutes after writing the entry warning about it.

---

Every one of those produced output that could be read aloud in a meeting without anyone objecting. That
is the property that makes them dangerous, and it is why this project spends so much of its effort on
things that make wrongness *loud*: typed errors instead of sentinels, `null` rather than `0` for an
undefined ratio, assertions that refuse rather than warn, controls in every probe, and a pre-flight dry
run before a twelve-night job.

**The habit that catches this class:** when a result is uniform, clean, or exactly what you expected,
print the raw value instead of reasoning about it. Both #5 and #18 were found that way, and neither
would have been found by thinking harder.

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
`M.A.P.-vault/.obsidian/workspace.json` — the vault's path at the time; it is `.obsidian/`
at the repository root now. Fixed with a `**/` prefix.

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


---

## 18 · The field whose name promised something it didn't hold

EDGAR's `index.json` lists a filing's files, each with `name`, `size` and **`type`**. The exhibit
lookup matched `type == "EX-99.1"`, which is exactly what that field looks like it holds.

It holds the directory-listing **icon filename** — `"text.gif"`, `"compressed.gif"`.

So the match never succeeded. Not intermittently: **for every filing, identically.** The pre-flight
dry run reported 350 of 350 items missing their exhibit, and that number is the dangerous part — a
uniform 100% failure reads as a *finding about the corpus* ("these filers don't attach EX-99.1") far
more readily than as a bug. It was one plausible sentence away from being written up as attrition.

The real document types live in the SGML submission header, served HTML-escaped inside
`{accession}-index-headers.html`.

**Same family as #5, the manifest version collision:** a field whose *name* implies one thing while
its *contents* are another, read confidently because the name was persuasive. In both cases the code
was correct about everything except what the data meant, and in both cases the fix began with printing
the raw value instead of reasoning about it.

**What made it survivable:** the dry run existed at all. Fetching 727 exhibits with zero LLM calls is
about thirty minutes; discovering this on night three of a twelve-night run is not.


---

## 19 · The context window nobody measured against the documents

Nine failures in the first hour of a twelve-night run, all one defect: an 8,192-token context window
against exhibits with a **median of ~9,070 tokens**. The run was not unlucky — it was going to fail on
**54% of the corpus**.

**How it got there.** Every test ran against a 470-character synthetic news file. Real Item 2.02
exhibits run 652 to 219,441 characters. Nothing anywhere compared document size to context capacity,
because at 470 characters the question never arises. The fixture was three orders of magnitude smaller
than the thing it stood in for, and being small is exactly what made it pass.

**The ninth failure hid inside a different name.** TSLA reported *budget exhaustion* after 6,699
reasoning tokens against a 12,000-token budget. It was the same bug: generation shares the window with
the prompt, so a 12,000 budget in an 8,192 window is unreachable, and the model stops at the context
ceiling while reporting that it ran out of budget. Two numbers set independently in different config
sections, contradicting each other, with the symptom naming the wrong one.

**Eight of the nine were classified transient.** They were HTTP 400s, and `InferenceStatusError` was
mapped to `other`. A context overflow is deterministic — it fails identically on every resume — so a
restart would have retried all eight, consumed the failure allowance again, and halted again. The
classification now reads the status *and* the message.

**The deeper lesson, which is the reusable one.** The fix was nearly a pre-flight comparing the
configured context to the estimated document size. That check would have **passed the failing run**:
config said 32,768, the estimate said 9,000, and the server was loaded at 8,192. Both numbers were
internally consistent and neither of them was the server. Context length is a server-side setting, in
exactly the sense KV-cache quantisation is — invisible to the cache key, invisible to the model
fingerprint, able to change behaviour without changing anything the repository can see.

So the pre-flight now **probes**: one deliberately oversized request per agent, rejected before any
generation, and the rejection states the real window. Same move as the grammar probe.

**Verify the thing, not your description of the thing.** A check between two of your own numbers
confirms your bookkeeping, not the world.


---

## 20 · The same mistake as #19, in the same session, with #19 already written down

Choosing context windows needed the memory cost of a KV cache. Rather than estimate it, I read the
architecture straight out of the GGUF: Gemma 4 keeps 40 of its 48 layers on a 1,024-token sliding
window and gives its 8 global layers a single KV head each. From those numbers the cache at 32,768
tokens is **0.87 GB**, which is what I reported and what the option was chosen on.

The server then refused to load the model at 32,768.

The runtime allocates full-length KV for **every** layer, ignoring the sliding-window bound the model
supports: about **336 KB/token**, so 11.0 GB at 32,768, against 7.0 GB of weights on a 16 GB machine.
My figure was wrong by **12.6×**, and wrong in the direction that made an unaffordable option look
comfortable.

**The architecture told me what is *possible*. It could not tell me what the runtime *does*.**

### The part worth recording

That is exactly incident #19 — *verify the thing, not your description of the thing* — and **#19 was
written up earlier in the same working session.** The lesson was in this file, freshly typed, while I
made the mistake it describes.

So the honest conclusion is not "now it is documented". It is:

> **A lesson written down is not a control.** Documentation records what was learned; it does not
> intercept the next instance. Only a mechanism does.

What actually caught this was not the note. It was the server refusing to load, and then a probe that
**measures the running system** — the bracket in ADR 0020 §4, which asks whether a prompt of a given
size is accepted rather than reasoning about whether it should be.

The pattern is consistent across #5, #18, #19 and this one: every time, the fix that worked was
replacing a derivation with an observation. The write-ups are useful for explaining *why* the
mechanisms exist. They are not a substitute for them, and treating a documented lesson as though it
were a guardrail is its own version of the same error — trusting a description of the system instead
of the system.


---

## 21 · The agent that expanded instead of compressing

Item 2 of the restarted clean band. STZ failed with a context overflow — on the **analyst's** 16,384
window, not intake's 32,768. The analyst's prompt was **22,368 tokens**.

The analyst never sees an exhibit. It reads intake's *compressed facts*, which had run 1,300–1,600
tokens across every previous run. Intake had been handed a 12,500-token document and emitted roughly
**20,000 tokens** from it. Intake's whole job is to compress, and **nothing capped what it could
emit** — `max_tokens` was unset, so its ceiling was its own 32,768 window.

### What the pre-flight actually checked

It verified every document against **intake's** window and stopped there. Each agent's budget had
been validated against its own context, and the *chain* between them against nothing. Both agents
were individually valid; the pipeline they form was not.

Two guards now exist:

- a startup validator that walks the chain — every agent's maximum output plus the next agent's
  template overhead plus its generation budget must fit its window. Numbers measured from real runs,
  not assumed: analyst template 1,229 tokens, structuralist 464.
- a **pre-dispatch assertion**: a rendered prompt larger than the receiving agent's allowance is
  refused before the request leaves, naming the agent that produced the payload and its size. The
  server's HTTP 400 says only that something did not fit, at the point where its origin is already
  lost.

### The subtlety that nearly broke the fix

The naive chain rule — *upstream `max_tokens` must fit downstream's window* — **rejects a working
configuration**. The analyst's 12,000-token budget is mostly reasoning that never leaves the model:
5,329 reasoning against 565 of visible narrative in one measured run. What crosses an agent boundary
is the visible output, not the token budget, and for a reasoning model those differ by an order of
magnitude. The chain is therefore checked against a declared visible bound, which the pre-dispatch
assertion enforces at run time.

### It had already happened twice, silently

Adding a `finish_reason` check surfaced two runs where a model had been cut off
mid-output and nothing said so:

- **intake on the STZ document**: 18,938 tokens, `finish_reason="length"`, the fact
  list ending mid-sentence on *"...for Corporate is not specified."* That truncated
  summary is what the analyst was then handed.
- **the analyst under the old 8,192 window**: 6,996 tokens, cut off, empty answer.

So STZ was not one defect but two stacked: intake expanded *and* its expansion was
silently truncated. The overflow that stopped the run was the second symptom; had
the analyst's window been slightly larger, the run would have continued happily on a
fact list that stopped halfway, and produced a schema-valid forecast from it.

**A cap without a check is a silent corruption.** Every agent's stop reason is now
recorded per call in the manifest and flagged per item in the ledger, in the same
shape as the document-truncation flag — because it degrades a forecast the same
way, and the observed 368-token maximum against a 2,048-token cap is exactly why it
must be visible rather than assumed absent.

### The lesson

Every previous context failure was about a *value* being wrong — a window smaller than configured, a
document larger than a window. This one was about a **boundary nobody owned**. Intake was correct in
isolation. The analyst was correct in isolation. The defect lived in the handoff, which no component
was responsible for and no check covered.

**Validating each component against its own constraints does not validate the pipeline.** The
interfaces between them need owners too, and the cheapest owner is an assertion at the point where
the payload changes hands.


---

## 22 · The flag that cried wolf, and the runaway it was pointing at

The `finish_reason` check added the day before reported **54 of 55 completed items truncated at
intake**. The reading was that every forecast in the run had been built on a fact list stopping
mid-sentence.

**Two of fifty-seven were.** The flag was wrong.

### Why the flag was wrong

The corpus runner built **one** `CountingTrace` for the whole band. `CountingTrace` accumulates per
stage and is never reset, so:

- `truncated_output` is a set. Once item 2 truncated, **every subsequent item inherited the flag** —
  including items whose own `finish_reason` was recorded, in the same manifest, as `stop`. A record
  contradicting itself, which is what should have been noticed first.
- `reasoning_tokens` sums. One manifest reported **272,033** analyst reasoning tokens for a single
  item — the band's running total.
- `JsonlTrace` fixes its path at construction, so **every item's events were written into the first
  item's directory** and the other 56 run directories had no `trace.jsonl` at all. That is the audit
  trail `CLAUDE.md` §6 requires, absent for 98% of the run.

Wiring is now built per item.

### What was actually happening

With the cap lifted, intake's output is remarkably flat:

| document | chars | intake output |
| --- | --- | --- |
| TSLA | 1,973 | 252 |
| AZO | 16,770 | 434 |
| HUM | 23,689 | 451 |
| SWKS | 27,255 | 434 |
| INTC | 42,980 | 451 |
| ALLY | 51,188 | 543 |
| **STZ** | 46,331 | **18,330, still going** |
| **FCX** | 131,879 | **3,533, still going** |

252–543 tokens across a 26× range of document sizes — and then two documents where it **runs away**.
ALLY is *larger* than STZ and produces 543 tokens; STZ produces 18,330 and has not finished. Size
does not predict it.

So the cap was never starving intake. Its job is to bound a runaway, and **a cap sized to "what it
wants" is meaningless when what it wants is unbounded.** The right response to a runaway is not more
room; it is to fail the item, because a fact list truncated at *any* cap is a fragment.

### The lesson

The instinct on seeing "54 of 55 truncated" is to fix the cap. The number was an artefact, and the
real defect — shared mutable state across items — was one level below it, corrupting three other
fields at the same time and silently deleting the audit trail.

**A measurement that surprises you is a claim about your instrument as much as about the world.**
The tell was already in the artifacts: a manifest saying `finish_reason=stop` and
`output_truncated=True` about the same call. Contradictory fields in one record beat any amount of
reasoning about what the model might be doing.

**The check still earned its place.** Without it, the two genuine runaways would have produced
schema-valid forecasts from fragments and been scored beside the rest. Making degradation visible
found a real defect *and* a false alarm — and the false alarm was itself a real defect.


---

## 23 · Not verbose — degenerate

Two items were failing intake at its cap. The question was whether the model was genuinely
verbose on those documents, in which case a bigger cap would help, or looping, in which case it
would not.

**Looping, unambiguously.** The 18,938-token STZ output:

| | |
| --- | --- |
| lines | 757 |
| **unique lines** | **22** |
| redundancy | **97.1%** |
| last new content | line **27** |
| most repeated line | **187×** |

Twenty-eight real facts, then a four-line block repeated ~180 times until the cap stopped it. FCX
is the same failure with a longer period: a ~22-line block repeating. Both are classic greedy-decoding
degeneration, and **size does not predict it** — ALLY is a *larger* document than STZ and produces
543 clean tokens.

So a bigger cap was never the answer. **A cap sized to "what it wants" is meaningless when what it
wants is unbounded.**

### The known fix works, and it is not free

Replaying the exact recorded prompts with a frequency penalty:

| item | penalty 0.0 | 0.3 | 0.6 |
| --- | --- | --- | --- |
| **STZ** | 2,048, cut off | **350, completed** | 640, completed |
| **FCX** | 2,048, cut off | **1,171, completed** | 492, completed |
| normal A | 222 (9 lines) | 420 (18 lines) | 394 (17) |
| normal B | 517 (27 lines) | 409 (21 lines) | 433 (19) |
| normal C | 159 (7 lines) | 197 (9 lines) | 172 (8) |

It breaks both loops cleanly. It also **changes every well-behaved item** — one nearly doubled in
length, another shrank by a fifth, and no normal output survived unchanged. Rescuing 2 items by
perturbing the inputs to the other 354 is the wrong trade; applying it only as a retry when
degeneration is detected is not.

The fix is [[decisions/0021-degeneration-retry|ADR 0021]]: a retry, not a default.
See #24 for the determinism gap the replay exposed on the way.

---

## 24 · Four reproducibility claims. Three hold; one does not, and it is measured

Replaying the two looping items ran the **exact recorded prompts** back through the
server at **temperature 0**. Every output should have come back byte for byte.
**Two of five did.** STZ and one normal item matched exactly; FCX and two others came
back close but not identical — FCX produced 53 lines both times, 21 unique then 22.

The value is not the defect. It is that "reproducible" was doing the work of four
separate claims, and only three of them survive contact with a measurement:

| claim | what it asserts | verdict |
| --- | --- | --- |
| **pre-registered** | the corpus was fixed before any result was seen | **HOLDS** — commit order proves it |
| **auditable** | every prompt and every response is preserved | **HOLDS** — now guarded (#22) |
| **replayable from cache** | re-reading a run returns byte-identical output | **HOLDS** |
| **re-derivable** | a cold cache reproduces the same forecasts | **DOES NOT HOLD** — measured |

The three that hold are the three that were ever actually being claimed; the fourth
is the one a reader supplies for themselves unless it is explicitly disclaimed. So
the README disclaims it, in these words:

> Temperature 0 is **near-deterministic, not deterministic**, on this backend —
> measured: 2 of 5 replays of identical prompts returned byte-identical output. A
> re-run from a cold cache will produce **similar** forecasts, not identical ones.
> What is exact is replay **from the cache**, which is why the cache is provenance
> infrastructure and not an optimisation.

`SamplingParams` already carried the honest version in a docstring — *"many local
backends ignore both; recording the request is honest, claiming reproducibility from
it would not be"* — written before any evidence existed. **It was right, and it was
also unenforced prose sitting next to a README that implied the stronger claim.** A
caveat in a docstring does not reach the person reading the abstract.

The stronger sentence is the specific one. "Reproducible" invites the question; "2 of
5 replays byte-identical" answers it, and is the one that can be defended in a room.

---

## 25 · A check in the wrong block turns one failed item into a dead run

The artifact verification of #22 was first written in the `try/except/else` of the
runner's attempt loop — in the **`else`** clause, which reads naturally: *run, and if
nothing went wrong, verify.*

`else` runs **outside** the handlers. A `MissingArtifactError` raised there is caught
by no `except` in that function, so instead of failing one item and continuing, it
propagates through the loop, past the ledger append, and out of the run. **The guard
against losing 56 traces would have ended the whole night on the first item that
tripped it** — and, worse, ended it *before* the ledger line was written, so the
failure it detected would not have been recorded either.

It belongs inside the `try`, where every other failure is classified. The rule that
falls out: **a check exists to classify a failure, so it must run where failures are
classified.** Anywhere else it is not a check, it is a new failure mode.

---

## 26 · The guard that compared one field of six

`verify_freeze` refuses to start a corpus run when the live configuration has drifted from
the frozen record. It had been passing for weeks. It compared the **model alias** and
nothing else.

So the frozen record said `intake.max_tokens: null` while every run since the cap was
introduced had been configured at 2,048, and `analyst.max_visible_tokens` was never
recorded at all. Neither value was wrong in the config — the **record** was wrong, and the
guard whose entire job is to notice that disagreement was looking at a different field.

This is [[decisions/0020-context-window-and-truncation|ADR 0020 §4]] one layer up. That
one says a pre-flight comparing `config` to a computed number would have passed the halted
run happily, *because both were internally consistent and neither was the server*. Here:
the freeze held a number, the config held a different number, **and nothing ever put them
side by side.**

It now compares every field the frozen record names, and reports all mismatches at once.

### What it cost to find, and what it bought

Nothing, and it was luck — the drift surfaced only because writing an amendment meant
reading the record by hand. A guard that under-checks has no failure mode of its own. It
just keeps returning green.

That is the reason for [[Guard Audit]]: one pass over every check in `src/`, asking of
each what its name implies against what it verifies. **Fifteen more gaps, eleven guards
confirmed sound, seven fixed** ([[decisions/0022-guard-scope|ADR 0022]]).

### The taxonomy is the finding

Fifteen gaps in fifteen places is a chore. Fifteen instances of **three shapes** is
something you can carry to the next guard you write.

**1 · Presence standing in for identity.** The check confirms something is there where
the name claims the *right* thing is there. The sharpest case: the trace guard written
*specifically for incident #22* verified that a non-empty file sat at the path. Under
that incident 56 runs had no trace and the 57th held every item's events — so the guard
would have caught the 56 empty directories and passed **the one artifact that was
actually wrong.**

**2 · A declared number trusted instead of the thing measured.** The check compares
against a value someone wrote down and treats agreement with it as agreement with
reality. This incident's own shape, and [[decisions/0020-context-window-and-truncation|ADR 0020 §4]]'s
one layer up. Also `max_visible_tokens`, a bound nothing enforces that a startup
validator treats as a guarantee — and `temperature == 0` standing in for reproducibility,
which [[Findings & Incidents#24]] measured as false.

**3 · Scope narrower than the sentence.** Correct about a smaller thing than the name
describes. "This band" with no band filter. A *band* failure rate enforced per
invocation. A two-point range measured where three-point distinctness is claimed. An
invariant with an unasserted escape.

### A fourth instance, from the same day, in my own reporting

Re-running the pre-flight took visibly less time than the first run, and I explained it
to Kamil as the exhibits being cached. **There is no HTTP cache anywhere in this
project** — `EdgarExhibits.fetch` goes to EDGAR every time, 712 throttled requests per
`--check`. The audit found that out two hours later.

That is shape 2 with no code involved: an observation checked against a mechanism I
believed existed rather than against the code, and agreement with the belief reported as
agreement with reality. It is worth recording next to the others because the failure mode
is identical and the medium is not. **A green check and a confident sentence fail the
same way.**

---

## 27 · The sensitivity check that could never exclude anything

`map evaluate` runs the two pre-registered robustness checks of
[[decisions/0020-context-window-and-truncation|ADR 0020]] and
[[decisions/0021-degeneration-retry|ADR 0021]] unconditionally — the primary result with and without the
truncated exhibits, and with and without the degeneration retries.

The partition keyed the excluded set on the ledger's `filing_date` and the scored items on the forecast's
`as_of`. **A forecast opens the day after the filing it reads**, so the two sets could not intersect. Both
checks would have reported *"no items in the set"* for the entire corpus, forever.

**A pre-registered check that can never fire is worse than no check at all.**

Not equivalent to it — worse. Having no robustness check is a visible gap. This one would have printed a
line, in the report, saying the result did not change when the truncated exhibits were excluded. Nothing
would have failed, no count would have looked wrong, and **we would have cited it.** An empty subset reads
as *nothing was affected*, which is not a null result — it is reassurance, manufactured, in the place where
evidence was promised.

Both pre-registrations were declared in an ADR before any score existed, precisely so they could not become
optional afterwards. They would have been discharged against nothing, and the discharge would have looked
like the strongest possible outcome.

Found by the test written for it, which is the entire argument of [[Findings & Incidents#The second lesson, which took three instances to see|the second lesson]]: the test asserted a subset of a *known* size, so it could tell "excluded 1 of 2" from "excluded 0 of 2". An assertion that the checks merely *ran* would have passed.

The pairing between a ledger entry and its forecast is now carried through the loader rather than
reconstructed from dates. **Two identifiers that are nearly the same are worse than two that are obviously
different** — `filing_date` and `as_of` are both dates, both about the same item, one day apart, and
comparing them type-checks.

---

## 28 · Three adapters, three ways to be plausibly wrong

Wiring `map evaluate` meant writing the join between stored artifacts and the scoring engine. All three
adapters had a natural implementation that is silently wrong ([[decisions/0023-scoring-adapters|ADR 0023]]).

**Scanning `runs/` would have scored the wrong corpus.** That directory still holds `first-capture`,
`first-capture-v2` and loose UUIDs from the first live forecasts — different prompts, a different horizon,
an older schema. Several would parse. The scored set comes from the ledger, which is the reasoning that
killed resume-by-scanning applied to the other end of the pipeline.

**Two of the three "fixes" were already safe, and safe by accident** — which is its own finding. The
vintage concern as originally raised (a split between forecast and scoring leaving the endpoints on
different bases) **could not happen**, and saying so mattered: recording the change as a repair would have
claimed a fix for a defect that did not exist. What it actually fixed was elsewhere.

- A split between forecast and scoring re-adjusts *both* endpoints, so `SpotDriftError` already fires on
  the recorded spot. The reachable vintage failure was elsewhere and unguarded: `ProviderChain` fails over
  **per call**, so one ticker can be served by yfinance and the next by stooq, and the price cache is keyed
  by `fetched_on`, so a pass spanning midnight mixes vintages.
- A future earnings date was already dropped, because the multiplier looks each date up in an
  already-truncated history and a future one simply is not found. **Silently.** An adapter handing over the
  full calendar looked correct, and would have kept looking correct until the day the history stopped being
  pre-truncated.

Both are the shape from [[Guard Audit]]: *safe by construction* is a claim about code, and code changes.
The contract now carries the as-of date, so a look-ahead is something a caller writes on purpose rather
than something it inherits.

### The baseline that would have been easy to beat

The first version fitted the earnings multiplier on the frozen corpus's own filing dates — no network,
already verified. Rejected on review, and the objection turned my own argument back on me: **a
poorly-fitted baseline flatters the result invisibly**, which is exactly why this project depends on `arch`
instead of hand-rolling a GARCH. It applies to the input as much as to the estimator.

The mechanism is worse than "fewer data points". `earnings_multiplier` sorts every window into *earnings*
or *ordinary*. A window the calendar fails to name **is not merely missing from the numerator — it lands in
the denominator**, raising the ordinary bucket's dispersion with exactly the windows the numerator exists
to isolate. The ratio is squeezed toward 1.0 from both ends, and a multiplier at 1.0 is the random walk
wearing a second name. The benchmark that exists to *widen for a scheduled event* would have declined to
widen, and beating it would have proved nothing.

The calendar now comes from EDGAR — complete over the fitting window, ~120 requests, cached. And the
weakness is measured rather than argued away: every item carries the multiplier it was fitted with, and
the report distinguishes *could not be fitted* from *fitted, and found nothing to widen for*.

**Writing the test for it found a bug in the cache I had just written.** The in-memory memo was keyed by
ticker while the fetched range depended on the as-of date — so the first item of a ticker fixed the
calendar, and every later item silently got one truncated to an earlier window. Scoring runs in ascending
date order, so the truncation would have hit *most* items of every ticker, biasing the multiplier in the
precise direction the whole change was made to prevent.

---

## 29 · The comment that justified a policy with a fact that was not true

`budget_exhausted` was classified transient, and `ledger.py` said why:

> The analyst samples at temperature 0.7, so a second attempt genuinely explores a different reasoning
> path and may finish inside the budget.

**`seed` is fixed for the analyst and goes on every request.** `attempt` reaches the cache key but never
the request body. So a retry sends a *byte-identical* request, and whether it explores anything at all
depends on the backend choosing to ignore the seed — which [[Findings & Incidents#24|#24]] measured as only
partially true.

The policy was resting on a coin-flip nobody chose, in the direction where being wrong costs a full
15-minute analyst call on every resume. [[Guard Audit|Shape 2]] again: a declared property trusted instead
of the thing measured. The comment was written when it was plausible and never re-read against the config
beside it.

**What made it visible was ALLY failing twice.** Nothing about the comment looked wrong; it looked like
careful reasoning, and it was — about a system that had a different `seed` setting.

### The rule that replaced it

*Transient* is a hypothesis about an item, and the ledger already holds the evidence to test it. A reason
that recurs on the same item twice has stopped being a hypothesis, so the item is resolved
([[decisions/0024-repeat-rule|ADR 0024]]). The retry is the experiment: flipping `budget_exhausted` to
terminal outright would have discarded the evidence, and leaving it transient collects the same evidence
forever without ever reading it.

Two observations do not prove determinism — at P(runaway) = 0.6 two hits happen 36% of the time — which is
exactly why the answer should be per item rather than per class.

---

## 30 · The bucket that would have made the fix worse than the bug

The repeat rule needed a prerequisite, and it was not obvious until the failure modes were laid side by
side.

A network failure fetching an exhibit raised `ExhibitError`, which the classifier did not match, so it fell
through to `other` — **the same bucket as a genuine model failure**. `httpx` invites this: a 404 from
`raise_for_status()` and a dropped socket both raise `HTTPError`, and one `except` clause reads as complete
coverage.

When DNS dropped, five items — WAL, BXP, CP, ELV, LVS — failed together and were recorded as `other`. Ship
the repeat rule without splitting that bucket and a **second** outage spanning two resumes burns all five
permanently. The mechanism built to stop one item wasting 15 minutes per pass would have silently deleted
five items from the corpus, and the deletion would have looked exactly like the intended behaviour.

The split is by what the failure says about the **item**:

| | says | repeat is evidence? |
| --- | --- | --- |
| `exhibit_unreachable` | EDGAR was never reached — a property of the afternoon | **no**, excluded |
| `exhibit_error` | EDGAR answered and refused — its view of this filing | **yes** |

The general form is worth more than the case: **before treating a repeated failure as evidence about a
thing, check that the failure is about that thing.** Five items failing together is a fact about what they
share, and what they shared was the network.

`MissingExhibitError` subclasses `ExhibitError`, so the classifier's `isinstance` order is load-bearing —
a filing with no EX-99.1 must not be reported as an EDGAR refusal, which would make a permanent absence
look like something a retry could change.

---

## 31 · The guard that would have been overridden every time

`map evaluate` refused to score a band produced by more than one commit. Sensible, and by the first real
pre-flight the band already spanned two — thirty-five items in, because development continues while a corpus
runs and does not stop for twelve nights.

So `--allow-mixed-code` would have been required on **every** scoring run.

**A check that must be overridden every time is not a check.** It is #27 from the other side. There, a
partition that could never fire read as reassurance; here, a refusal that always fires trains you to wave it
through — and the run where it means something looks exactly like the eleven before it.

The fix was to notice the guard was asking the wrong question. Not *which commit produced this item* but
*did anything a forecast depends on differ* — a hash over the forecast-producing files, recorded beside the
commit ([[decisions/0026-forecast-digest|ADR 0026]]).

### "It can't be done retroactively" was wrong, and the reason matters

I said the 35 existing items could not get a digest. They could. The digest is a pure function of file
contents at a commit, and every manifest already records its commit — so `git ls-tree` recovers it exactly.

The distinction is between **computing a function of recorded data** and **inferring data that was never
recorded**. The second is what made deducing a run's identity from timestamps wrong. I had generalised a
correct rule about inference to a case that was not inference, and the generalisation cost nothing only
because someone checked it.

### The honest residual

The digest is file-granular. It answers *did any file that can produce a forecast change*, not *did the
behaviour change* — undecidable without running both.

It is already binding: the band's two groups differ by exactly three files, and the whole difference is
scoring-side additions that cannot touch a forecast. Tightening the exclusion list until that split vanished
would be choosing the rule after seeing the result. So the split stands, and the refusal now **names the
differing files** — which turns the override from a flag you learn to pass into a judgement you can make in
one glance.

---

## 32 · The halt reintroduces the confound the pass design was built to prevent

Projecting the failure rate forward showed the clean band halting somewhere between item 208 and 312. The
obvious question was how much power survives. The answer is that a halt at 312 costs nothing measurable and
a halt at 208 takes calibration power at the decision-relevant k from 73% to 53%.

**The more serious cost is not power.** `plan()` orders items by `(filing_date, ticker)`, so a halt does not
take a random subset of the band — it takes a **prefix of the year**. A halt at 208 keeps January to May 5
and loses May through August entirely.

That is precisely the confound `passes.py` exists to prevent. Its own docstring:

> Taking the first half of the plan and calling it pass one would make it a calendar-contiguous subsample —
> roughly H1 of the band — so stopping after it would confound "we stopped early" with "we only measured
> the first half of the year".

**The interleaving was built for the two-pass ambiguous band. The clean band runs straight through** — and
the clean band is the one carrying the primary result. A protection was designed, reasoned about, written
down, and installed on the band that needed it less.

Nothing was wrong with the pass design. The gap is that "what does an early stop leave" was asked of the
band that was *planned* to stop early, and never of the band that might stop early by accident.

It is recorded rather than fixed: re-ordering now cannot un-bias the 78 items already run in date order, and
changing execution order partway is its own confound.

---

## 33 · Sized on 344, reported on 90

Computing the halt power meant reproducing ADR 0018's published table first, so the numbers would be
comparable. The design that reproduces it — 100% at k=0.2, 92% at k=0.5, 32% at k=0.8 — is **120 tickers ×
3 dates on a reportable subset of ~90**, not on the 344 forecasts the ADR names in the same sentence.

Both numbers are correct and the ADR states both. But "the primary result is calibration on the clean band,
at 120 × ~2.87 ≈ 344 forecasts. Power: 100% at k=0.2…" reads as though the power belongs to the 344. It
belongs to the quarter of it that is reportable after the holdout and post-cutoff splits.

`power.py`'s own docstring names this as the failure it exists to prevent — *"sizing on the full corpus and
reporting on a quarter of it"* — so the module was right and the sentence summarising it was ambiguous. **A
correct number in a sentence that invites the wrong reading is a reporting defect**, and this one would have
been repeated into the write-up by anyone reading the consequences list rather than the module.

---

## 34 · The protection was built, argued for, and installed on the other band

Projecting the failure rate forward showed the clean band halting somewhere between item 208 and 312, so I
computed how much power survives. The power answer was mild. The thing beside it was not.

`plan()` orders by `(filing_date, ticker)`, so a halt takes **a prefix of the year**. At item 208 that is
January to May 5 — **May, June, July and August absent entirely.**

`passes.py` already contained the argument for why that is unacceptable, written before any of these
failures:

> Taking the first half of the plan and calling it pass one would make it a calendar-contiguous subsample
> — roughly H1 of the band — so stopping after it would confound "we stopped early" with "we only measured
> the first half of the year".

**The protection was designed, reasoned about, written down — and installed on the ambiguous band.** The
clean band, which carries the primary result, runs straight through.

Nothing was wrong with the pass design. The gap is that *"what does an early stop leave?"* was asked of the
band **planned** to stop early, and never of the band that might stop early by accident. A question asked
in one place and not the other, where the second place was the one that mattered.

### I proposed to record it rather than fix it, and that was wrong

My reasoning was that re-ordering cannot un-bias the items already run, and that changing execution order
partway is its own confound. The first is true and the second is not — and Kamil's push-back carried the
argument I should have made myself:

- **No score exists anywhere yet**, so nothing here can be tuned toward a result.
- **Applying a documented principle where it was missed is the opposite of tuning**, and it is the same
  move that made backfilling the forecast digest legitimate.
- **Execution order cannot reach a forecast**: `as_of` comes from the filing date, the vintage is pinned,
  sampling has a fixed seed, the cache is keyed on content. It determines only which subset survives.

I had generalised "don't change the protocol mid-run" — a good rule — past the case it covers, exactly as I
had generalised "don't infer unrecorded data" past the digest backfill a day earlier. **Twice now the
over-general form of a correct rule has been the thing standing in the way**, and both times the cost of
being wrong was invisible until someone pushed.

The remainder is now executed in a seeded shuffle ([[decisions/0028-execution-order|ADR 0028]]). The result
is a hybrid — 80 contiguous early items plus an interleaved remainder — stated as that rather than dressed
as a clean design. At a halt near 210 all eight months survive with January over-weighted about 1.7×, which
is a distortion that can be stated and weighted. The prefix lost three months, and no weighting repairs an
absence.

---

## 35 · Two bugs found by running the pre-flight against reality

Running `map corpus run --check` while the band was in flight — to confirm the freeze amendment landed
cleanly — produced two lines that should not have been there.

### A `for` loop between an `if` and its `else`

```
resume     skipping 134 of 356 items (132 complete, 1 terminal, 1 retries exhausted) — 222 to run
           ALLY 2026-01-21: budget_exhausted twice — not retried again
resume     nothing recorded; all 356 items to run
```

Both branches printed. Adding the "name each exhausted item" loop between the `if` block and its `else`
rebound the `else` to the **loop**, and Python's `for/else` runs whenever the loop is not broken out of —
which is always. So every resume also announced that nothing had been recorded.

Nothing failed. The counts were right, the ALLY line was right, and a contradiction sat between two correct
statements. `for/else` is the one Python construct where inserting a loop silently changes what an adjacent
keyword means.

### A busy server reported as a small one

```
context    intake: rejected a prompt of ~32,512 tokens, so its window is under the configured 32,768 [TOO SMALL]
```

All three agents, on the exact windows the running band was succeeding with at that moment.

The probe brackets: send a prompt just under the configured window (must be accepted) and one well over
(must be rejected). **A busy server rejects the under-probe exactly as a too-small window does**, and
bracketing cannot separate them. The verdict was not merely wrong — it was wrong in the direction that
invites a harmful fix, since the printed remedy is *"lower it in config"*, and lowering a context that is
fine would have re-derived which exhibits fit against a fiction.

The fix is a **canary**: a 64-token prompt no configured window can refuse. If even that is rejected, the
window was not measured, and the report says `UNMEASURED` with the opposite remedy — stop competing for the
server. It is [[Findings & Incidents#8|finding #8]] again: a check that cannot distinguish two causes will
confidently report one of them.

**The general shape, which is the part worth keeping.** Both bugs were invisible to the test suite and
obvious the moment the command met a real, busy machine. A pre-flight is a thing you run against reality, so
its own failure modes only appear there — and this one had been run twice before, both times against an
idle server.

---

## 36 · The same guard, the same failure, one layer up — and the fix reintroduced it in a label

`map evaluate` refused a band spanning two frozen records, with no override, because two records meant "two
items were not asked the same question."

Amending the freeze to record the execution order took it from 2.3.0 to 2.4.0. **Every field deciding what a
model is asked stayed byte-identical.** So the guard would have refused every band from the next restart
onward — [[Findings & Incidents#27|#27]] from the side it bit last time, and the same defect
[[decisions/0026-forecast-digest|ADR 0026]] had already fixed for the commit, one layer up and eight commits
later.

The lesson is not "check the freeze too". It is that **a version number is never the right equality test**,
because a version increments for editorial reasons and the thing you care about is content. Both times the
guard compared an identifier that moves for reasons unrelated to what it is guarding.

### Two things the tests caught that review had not

**A field classified as neither.** The split is a governing list and a recorded-only list, and a test asserts
every field of the real record appears in one of them. It failed immediately: `amends` was in neither, from a
typo, and a field in neither list is **silently excluded** — the invisible direction, where a real difference
reads as agreement. Nothing else would have said so.

**The fix reintroducing the bug in a display string.** The group label was built as
`f"{digest[:12]} (v{version})"` — so two runs with an identical digest under different versions produced two
*different labels* and were counted as two groups. The refusal fired for exactly the reason it had just been
built to stop firing.

That one is worth sitting with. The key and the label were the same string because it was convenient. **A
grouping key that doubles as a display string will eventually be given something display-only**, and the
guard changes meaning without anyone editing the comparison.

---

## 37 · "Below anything observed" — with two observations

PRU overflowed intake's window *after* truncation. The document was cut to 98,121 characters, estimated at
~28,035 tokens against a 29,968-token budget, and the server refused it.

[[decisions/0020-context-window-and-truncation|ADR 0020]] had priced exactly this and dismissed it: the
margin "covers ratio error down to about 3.3 characters per token, **which is already below anything
observed** (3.7 and 4.0 from real rejections)."

Two observations. Both from rejected oversized prompts — which is a biased sample, because a document is
more likely to be rejected when it tokenises *densely*, so the two points came from the part of the
distribution most likely to be atypical. Measured across 135 completed items:

| min | p05 | median | max |
| --- | --- | --- | --- |
| **3.017** | 3.285 | 3.887 | 5.095 |

**14% of documents tokenise below the assumed 3.5, and 6% below the 3.3 that was "below anything
observed."** A 98,121-character cut fits only if the true ratio is ≥ 3.274. So about one truncated exhibit
in twenty was always going to fail. PRU is not bad luck; it is the 6% arriving on schedule.

### The estimator pointed the right way and then took the wrong value

`estimate_tokens` divides by the ratio, so a **higher** ratio predicts **fewer** tokens. ADR 0020 knew this
— it says the gate "uses the low end of that range, because financial prose tokenises worse than ordinary
English." The reasoning about direction was right. The value was the low end *of two points*, which landed
near the middle of the real distribution.

A refusal gate needs to sit at or below the floor of what it gates. 3.5 sits at roughly the 12th percentile
from the wrong side.

### The lesson is about the phrase, not the number

**"Below anything observed" is a claim about your sample, written as a claim about the world.** It is only
as strong as the number of observations behind it, and that number was not in the sentence. Had it read
"below both of the two ratios observed so far", nobody would have leaned on it.

The repair that generalises: when a margin is justified by an observed range, **state n in the same
sentence**. It is the same defect as [[Findings & Incidents#The third lesson: a true sentence can still mislead|#33]] —
a true statement whose form invites more confidence than its evidence supports.

And the structural fix is not a better number. It is that a margin chosen from a sample must be **backstopped
by a measurement**, so that when the sample turns out to be unrepresentative the failure is loud and early
rather than silent and at item 136.

---

## 38 · The judgement that is cheap now and expensive later

The forecast digest refuses a band spanning two code states and hands over the differing files, so the
override is made on evidence rather than blind. **That still leaves a judgement, and the honesty of a
judgement depends on when it is made.**

At scoring time it stands between a person and a result they have spent two weeks producing. *"These files
look like plumbing"* is a much easier sentence to believe under that pressure, and every incentive points
one way. So every boundary in the clean band was adjudicated now, with no forecast scored anywhere
([[decisions/0030-code-boundary-adjudication|ADR 0030]]).

The pattern is the same one the two-pass band and the sensitivity partitions rest on: **a decision that is
free to make honestly beforehand becomes expensive afterwards, so the time to make it is the only variable
you actually control.**

### "Cannot tell" had to be a permitted answer for the other two to mean anything

One boundary is adjudicable: three files differ and all three are additions consumed only by scoring, so it
could not have changed what a model was asked. One is not: 34 items came from an uncommitted tree, and the
files that executed are unrecoverable.

For the second I could reconstruct a plausible story — I know what I was editing, and the committed span on
either side touches no prompt, no sampling field, no request body, no cache key, no document handling and no
tokeniser. Every one of those checks passes. **None of it rescues the group**, because the committed span is
not what ran, and what I remember editing is memory rather than record.

Had "cannot tell" not been available, the pressure would have been to write "could not have changed" and
lean on the six clean checks. **A verdict set with only two options is a verdict that will be forced**, and
the third option is what keeps the first two from being rubber stamps.

### The over-inclusion is not the digest being wrong

Worth stating because it will be tempting to read it the other way. Boundary 1's three files —
`config/default.toml`, `settings/loader.py`, `bootstrap.py` — carry every context window and sampling
parameter in the project. They belong on the governing side. A diff that turns out to be one new cache key
is the **price of that correctness**, not evidence the classification is too broad.

The digest answers *did any file that can produce a forecast change*. It was never going to answer *did the
behaviour change* — that is undecidable without running both — which is exactly why the human judgement
exists, and why it is written down before anyone has a reason to want a particular answer.

---

## 39 · One shape, six instances: a representation that cannot hold the state it must distinguish

Six failures look unrelated. They are the same defect — and the sixth is a variant.

| the identifier | the two states it had to tell apart | what happened |
| --- | --- | --- |
| `head_tail_v1` | a 3.5 chars/token basis vs a 3.0 one | the same string named both; documents cut to 98,121 and 84,121 characters carried identical labels |
| the **freeze digest** | *was not truncated* vs *would not be truncated* | three items that fit whole at 3.5 carried the untruncated digest, so a ratio change that would now cut them was invisible |
| the **ledger** | *never attempted* vs *deliberately invalidated* | forcing a re-run meant deleting lines from an append-only log, which also erased BXP's genuine transient-failure history |
| the **`--check` stale line** | *nothing is stale* vs *the check never ran* | it prints only when the list is non-empty, so a clean report and a silently skipped one are the same output — an absence of text |
| the **leakage line** | *the band being scored* vs *the band compared against* | the display hardcodes "clean" for whichever band was scored, so `--band ambiguous` prints "clean X vs clean Y" and inverts `suggests_leakage` |
| **`prices.fetched_on`** | *the vintage these prices came from* vs *the vintage we intended* | all 701 manifests record `2026-08-14`; no price was ever fetched on that date, and the cache is keyed on the real calendar day in every code path |

**Each is a representation that collapses two states the system must distinguish. And
each failed silently, for the same reason: the missing state had no encoding in which
to be wrong.** There was no field that could hold a contradiction, so nothing could
contradict. A check can only catch a disagreement between two things that were both
written down.

### The sixth is a different animal, and worse

The first five collapse two states into one encoding: the field cannot express the
distinction, so nothing can contradict. **The sixth records a state that never
existed.** `prices.fetched_on: 2026-08-14` is not ambiguous — it is false, in 701
manifests, and has been since the corpus began.

The mechanism: `ParquetPriceCache` *has* a `today` injection point, designed for
exactly this. It is constructed in one place (`bootstrap.py:69`) **with no `today`
argument**, in every code path including the corpus run, so `_path` always
namespaces on the real calendar date. The `today=config.price_vintage` at
`runner.py:569` never reaches the cache; it reaches `run.py:156`, where
`fetched_on = today or as_of.date()` writes it into the manifest. **The pin is a
label.** The corpus was fetched across at least seven daily snapshots — 08-28,
08-30, 08-31, 09-01, 09-02, 09-03, 09-04 — and there are zero files under 08-14.
`map corpus run --check` prints `vintage 2026-08-14 (pinned)` and reports a pin
that no code implements.

**What actually protected the result was `SpotDriftError`, not the label.**
`realised_return` refuses to score if the recorded spot has moved from the series
by more than 1e-4 relative, so a genuinely changed price fails loudly instead of
scoring wrong. Checked empirically on 2026-09-04: across the 178 clean-band dev
items, the spot bar and the realised bar agree **to the cent between the 09-02 and
09-04 snapshots, 178 of 178**, with the realised bar landing on the same date in
every one. The published result was never at risk. It was protected by a live
guard, while a dead one took the credit.

**The lesson is narrower than "check your labels".** A recorded field that no code
reads is not documentation, it is an assertion nobody verifies — and the longer it
sits there being wrong, the more load it silently takes. The fix is not to make the
label true but to make the pin real: pass `today=` at the one construction site,
so the field describes something.

---

The fourth is the mildest and the most general, and it is the one most likely to recur,
because **it is the default style of almost every command-line tool**: report problems,
stay quiet on success. That is fine when the reader is watching the exit code. It is not
fine when the line is a *gate* — and this one was, since scoring was conditional on
`stale 0`. A gate that passes by printing nothing cannot be distinguished from a gate
that was never reached, and the reader supplies the reassuring reading for free.

It was confirmed by computing the count independently rather than by reading the absence
— every completed clean-band item's recorded elision against what the current rule
produces, 351 checked, 0 stale — which is the right response to a missing signal but not
a substitute for the signal existing. **The rule this yields: a check whose result gates
a decision must state its result, including when the result is zero.**

The digest one is worth stating carefully, because it looks like a bug in the digest and
is not. **A content hash records the input that *was* used. It cannot represent an input
that *would* have been used under a different parameter.** FCX 2026-04-23, CP 2026-04-29
and CP 2026-07-29 fit whole at 3.5, so the drift never touched them and there was
nothing for a hash to differ about. **A digest detects a parameter change only where the
parameter bit.** The instrument that found them is the staleness check, which compares
each item against what the current rule *would* produce — a different question, needing
a different tool.

### The fix for the ledger, since it is the one still open

`head_tail_v1` now carries its parameters, computed from them so it cannot disagree
([[decisions/0020-context-window-and-truncation|ADR 0020]]). The digest limitation is
inherent and the staleness check covers it. The ledger is still a log you delete from:

> **Invalidation appends a supersession record** — item, reason, the commit or freeze
> amendment that invalidated it — rather than removing lines. **`resolved()` treats a
> superseded item as needing a run**, exactly as an unresolved transient failure is
> treated. **Nothing is ever deleted from an append-only log**, so the history of an
> item that was re-run three times remains legible, and "this item was invalidated by
> amendment 2.6.0" becomes a fact in the record rather than an absence.

The current mechanism is `rm` on a line, which destroys the evidence that the item was
ever attempted — and the append-only design exists precisely to keep that. I noticed
because deleting BXP's lines to force its re-run also erased its DNS failure from the
band's history; it survives only in a backup I happened to take.

---

## 40 · The runaway is content, and the corpus contains its own control

Four items ran the analyst past its entire 12,000-token reasoning budget. The obvious
hypothesis is that they are long documents.

**They are not, and the corpus proves it against itself.** Every one of these companies
files quarterly, so each failing document has same-company, same-template siblings:

| ticker | failed at | a **larger** sibling that passed |
| --- | --- | --- |
| ACGL | 39,253 | 39,655 — and 39,218 passed, **35 characters smaller than the failure** |
| WH | 39,902 | **48,922** |
| CHD | 34,467 | **41,187** |
| JAZZ | 32,599 | **41,625** |
| ATI | 36,261 | **37,979** |

**Five of six failures have a strictly larger same-company sibling that terminated
normally.** All but ALLY's sit between the 53rd and 73rd percentile of corpus document
size, against a median of 31,751 characters and a maximum of 219,441. None of them is a
large document.

So *raise the budget* was never the remedy, because there is no size problem to solve.
Whatever these documents do to the analyst is a property of **content**, and it is the
same question [[decisions/0021-degeneration-retry|ADR 0021]] answered for intake by
counting unique lines.

**The control group is now written down before the diagnosis runs**, which is the point
of recording this now rather than after: the comparison is a failing document against
its own company's passing sibling, on redundancy rather than length. If the failure's
reasoning repeats and the sibling's does not, it is degeneration on that content. If
both look alike, it is not — and that would be a finding too.

---

## 41 · Twelve HTTP requests that killed an hours-long experiment

The analyst runaway looked like the intake runaway, so the hypothesis was the same:
these documents are repetitive and the model gets stuck in them. The plan was to replay
the failing prompts and count repeated lines in the reasoning.

**Measuring the documents first took minutes and falsified it.** Six failing exhibits
and a passing same-company sibling for each, fetched directly, hashes checked against the
frozen record:

| | failures | siblings |
| --- | --- | --- |
| gzip ratio *(lower = more redundant)* | 0.306 | **0.300** |
| duplicate-line fraction | 51.8% | 51.9% |
| repeated 8-gram fraction | 9.5% | **10.9%** |

**Redundancy does not separate the two groups**, and on two of three measures it leans
the wrong way. Two of six failing documents are more compressible than their sibling;
one of six has more repeated 8-grams.

**A null is worthless unless the measure had range, so that was checked before the result
was believed.** Across the twelve documents the measures vary by 5× to 47× the
failure/pass gap, so they are not saturated. And a positive control — the corpus's
largest exhibit (BXP, 219,441 chars) against its smallest (IREN, 652) — separates on all
three, with gaps of 0.192, 0.503 and 0.122 against within-set spreads of 0.065, 0.094 and
0.070. So the wording is **"not detected by measures with demonstrated range"**, which is
a falsification. Had the control failed it would have been *"measures inadequate,
hypothesis untested"*, and the twelve-document result would have been void — the
distinction being exactly [[Findings & Incidents#8|#8]]'s vacuous positive control.

### Two lessons, and the second is the sharper one

**Measure the cheap thing first.** The replay is hours of a 12B model. The document
measurement is twelve HTTP requests and no inference. They test different links in the
same causal chain, and the cheap one sat upstream — had it come back positive, the replay
would have been confirmation rather than discovery; coming back negative, it saved the
hours outright.

**And a falsified hypothesis has to be scoped precisely or it destroys more than it
should.** What is dead is *"redundant input causes the runaway"*. What is untouched is
*"the reasoning degenerates"* — the [[decisions/0021-degeneration-retry|ADR 0021]]
intake finding measured the model's **output** (757 lines, 22 unique), and nothing here
measured any output at all. The two claims are one word apart and it would have been easy
to write "the degeneration hypothesis is dead" and abandon the right experiment for the
wrong reason.

### What the replay became

Not "is this input repetitive" — answered — but "does this model's reasoning repeat", at
five draws per document rather than one, because the analyst samples at temperature 0.7
and **a single re-issue is one draw, not a reproduction.** Five draws surface a per-draw
runaway probability of 0.3 or more with 83% chance and cannot distinguish 0.05 from zero;
that is written into the script above the code, so the result is read against what it
could have shown.

---

## 42 · The basis moved underneath a finished band

The clean band ended at 349 of 356. Then PRU overflowed its context **after** truncation —
cut to 98,121 characters, estimated at 28,035 tokens against a 29,968 budget, and refused.

Correcting the ratio from 3.5 to 3.0 was straightforward ([[Findings & Incidents#37|#37]]).
Working out **what it had already changed** was not.

**The reported stale set went 2 → 5 → 6, and each correction came from someone asking a
better question rather than from a check firing.**

- **2** — what the staleness check had reported when it last ran, at item 136. The band
  then ran for days.
- **5** — items whose *freeze digest* differed. Wrong instrument.
- **6** — what the staleness check said when actually re-run against the finished band.

The three the digest missed — FCX 2026-04-23, CP 2026-04-29, CP 2026-07-29 — **fit whole
at 3.5 and are truncated at 3.0.** They recorded `elided=0`, took the untruncated digest,
and sat in the majority group looking identical to 340 untouched items.

### Why a digest structurally could not have found them

**A content hash records the input that was used. It cannot represent an input that would
have been used under a different parameter.** Those three had no truncation to hash — the
drift never touched them — so there was nothing for a hash to differ about. **A digest
detects a parameter change only where the parameter bit.**

The instrument that found them asks the other question: *what would the current rule
produce for this item, and does it match what was recorded?* That is a comparison against
a counterfactual, and no amount of hashing gets there.

Both tools were already built. The mistake was reaching for the one that was fresh in mind
rather than the one that answered the question — and it was caught only because the count
was challenged twice.

### What it cost, and what it did not

Nine items re-run: six stale, two relabelled whose prompts were byte-identical and
**verified present in the response cache** before running, and PRU. PRU passed, so failures
fell to five.

**No forecast was scored under a mixed basis**, which is the whole reason this was worth
stopping for. The corpus is now on one truncation basis, and `head_tail_v1` carries its
parameters so two bases can never again share a name.


---

## 43 · I read a histogram and called it a tilt

> `[superseded 2026-09-05 -> Timeline §16]` — figures are the 178-item development half on the 2026-09-02 vintage. The finding stands; the numbers are superseded.

Reporting the first development scores, I described the PIT as "tilted, not U-shaped",
on the strength of the bottom bin holding 28 items against 17.8 expected.

**Tested, the tilt is not there.** Mean PIT is 0.4893, and the cluster-robust interval
is [0.4098, 0.5423] over 178 items and [0.3964, 0.5371] over the 18 occupied blocks.
Both cover 0.5 with room to spare.

Two things went wrong, and they are both structural rather than careless:

**Ten bins are ten chances.** One bin in ten will sit outside its 90% range by
construction, and the eye goes to whichever one did. Reading a shape off a histogram is
not a free look at the data — it is an implicit test with an unstated multiplicity
correction of one.

**The naive standard error was never computed, and would have been wrong anyway.** With
178 items in 18 date clusters, the independent-draw error is far too small. The interval
that matters had to come from the same moving-block bootstrap the CRPS comparisons use,
and once it did, the tilt evaporated.

### The shape does depart, but not where I said

| statistic | value | verdict |
| --- | --- | --- |
| mean PIT vs 0.5 | 0.4893, both intervals cover | no tilt |
| KS *D* | 0.0726, p=0.291 under independence | nothing |
| **Anderson–Darling *A²*** | **3.044** vs 2.492 at 5% | **departs** |

**KS and A² disagree, and the disagreement is the finding.** KS is driven by the largest
vertical gap between the empirical and uniform CDFs, which for a symmetric departure sits
in the middle where the two curves cross anyway. A² carries a 1/(u(1−u)) weight and is
built for the ends. A distribution correct in the body and thin in the tails is precisely
the case KS is blind to — and precisely what a mis-scaled forecast produces.

Both p-values assume independent draws, so both read high on a clustered panel. Neither
is the test; the tilt interval is. A² is reported as a descriptor that points at *where*
to look, and where it points is the tails.

**The lesson is not "look harder at histograms".** It is that a picture with ten
categories cannot make a claim, and the fix is to state the statistic before looking —
which is what the tilt interval and A² now are, computed unconditionally on every scoring
run rather than reached for when a bar looks tall.

---

## 44 · The calibration ratio and the PIT disagreed, and both were right

> `[superseded 2026-09-05 -> Timeline §16]` — figures are the 178-item development half on the 2026-09-02 vintage. The finding stands; the numbers are superseded.

`stated sigma / realised = 0.733 [0.637, 0.798]` says clearly under-dispersed. The PIT
says the body is fine. These are not compatible readings of one distribution, so one of
them had to be wrong — and neither was.

**They weight outcomes differently.** The ratio is a quotient of root-mean-squares, so it
is dominated by the largest moves. The PIT is rank-based and hardly notices them: an
outcome at four sigma and an outcome at forty both land in the top bin.

| | value | calibrated |
| --- | --- | --- |
| MAD-based scale of `z` | 1.079 | 1.0 |
| median &#124;z&#124; | 0.7445 | 0.674 |
| RMS `z` | **1.324** | 1.0 |

**The top five outcomes carry 28.5% of the sum of squared returns.** Excluding them moves
the ratio from 0.733 to 0.843.

| ticker | date | return | sigma | z |
| --- | --- | --- | --- | --- |
| CELH | 2026-02-27 | −0.222 | 0.048 | **−4.64** |
| INTC | 2026-04-24 | +0.188 | 0.047 | **+4.00** |
| IONQ | 2026-05-07 | +0.187 | 0.066 | +2.83 |
| CORZ | 2026-07-29 | +0.184 | 0.073 | +2.50 |
| IONQ | 2026-01-27 | −0.168 | 0.066 | −2.56 |

So the model's dispersion is **right in the body and much too thin in the tails.** That
is excess kurtosis in the outcomes, not a scale error — and the distinction is not
academic, because it decides what a correction may be fitted on. A scale factor fitted to
the RMS ratio would widen every sigma by about 36% to accommodate five events, leaving
173 items over-dispersed while the headline ratio read 1.00 exactly. The correction would
score *worse* on every rule that weighs items equally, and better on the one number
anybody would quote.

Pre-registered in [[decisions/0032-calibration-form|ADR 0032]]: the scale is fitted by
minimising the development log score, never the ratio.

**A statistic that aggregates is not a diagnosis.** 0.733 was a true fact that supported
a false conclusion, and the only reason it did not become a fitted correction is that the
two instruments were reported side by side and disagreed loudly enough to check.

---

## 45 · An open hypothesis that the evidence does not currently support

Recording this because the *test* was designed before the result came in, and a
hypothesis discarded for the right reason is worth as much as one kept.

**The issuer-promotion hypothesis.** Every exhibit in the corpus is an EX-99.1 earnings
release — the issuer's own promotional text about its own quarter. If a model reasons
from that document, the design predicts a **bullish skew**: the forecast should sit above
the outcome on average, and the PIT should tilt low.

**The corpus shows no such tilt** (finding #43), so the hypothesis is *not* recorded as
live, and no mechanism story is being told about a pattern that has not been established.

It is worth keeping written down because **this corpus structurally cannot test it.**
Document type does not vary: every item is the same genre from the same author about the
same author. A null here is uninformative about the mechanism — there is no contrast, so
there is nothing for a skew to be *relative to*.

**What could test it:** the same tickers and dates, forecast from a document type the
issuer did not write — a wire-service summary, an analyst note, or the 8-K body stripped
of the exhibit. The comparison is the skew of one against the skew of the other, paired
by ticker and quarter. That is a second corpus, not a re-analysis of this one, and it is
the natural companion to the ablation in #46.

---

## 46 · The system declines to commit to a direction — an architecture result, not a scoring one

> `[superseded 2026-09-05 -> Timeline §16]` — figures are the 178-item development half on the 2026-09-02 vintage. The finding stands; the numbers are superseded.

| | |
| --- | --- |
| P(up) span | 0.369 – 0.631 |
| median | 0.513 |
| directional accuracy | 50.0% (89 of 178) |
| Brier vs a coin flip | indistinguishable |

The easy reading is that Brier is a weak rule or that direction is hard. Neither is what
this says. **The forecasts barely leave the neighbourhood of 0.5.** A model that never
claims a direction cannot be right or wrong about one, and the Brier result is a
restatement of the P(up) span rather than independent evidence about skill.

The three baselines cannot arbitrate, because all three set drift to zero by
construction — so each predicts P(up) = 0.5 exactly and the comparison is against a coin
flip, once, not against three benchmarks.

**Why this is an architecture question.** The pipeline is Intake → Analyst → Structuralist,
and the analyst is asked for three scenarios with probability weights. A near-0.5 P(up)
is what you get when the bullish and bearish scenarios come back close to symmetric —
which may be the analyst genuinely finding no signal, or may be an artefact of *asking
for three scenarios in the first place*. A prompt that requests a balanced set may be
answered with a balanced set regardless of the document.

Those two explanations make different predictions, and the ablation already planned for
Phase 3 separates them: run the structuralist directly on the intake summary, with no
analyst, and compare the P(up) spans. If the span widens without the analyst, the
three-scenario frame is compressing the directional claim. If it does not, the flatness
is in the model's reading of the document and the frame is innocent.

**This is what makes the ablation the next experiment worth running** rather than the
tidy-up item it has been since Phase 1. It has a specific prediction to test, on a
quantity that has now been measured.

---

## 47 · The leakage line labelled both bands "clean", and a display artifact caught a logic error for the second time

Running `map evaluate --band ambiguous` to produce the headline number printed:

> `leakage: clean 0.03330 vs clean 0.03189, difference +0.00141`

**Both figures labelled clean.** One of them is the ambiguous band. The tell was
visual — a label repeated where two different labels belong — and it exposed a real
inversion underneath.

`_leakage` passes the band **being scored** as the first argument. `LeakageEstimate`
documents that argument as the clean band, and `suggests_leakage` is `lower > 0` on
`first − second`, which is a leakage signal only when the first is clean. So:

| invoked as | `difference` is | `suggests_leakage` fires when |
| --- | --- | --- |
| `--band clean` | clean − ambiguous | ambiguous scores **better** ✓ correct |
| `--band ambiguous` | ambiguous − clean | ambiguous scores **worse** ✗ inverted |

The estimate is correctly oriented and correctly labelled **only when the clean band
is the one scored**. Run the other way it inverts silently, and the display hardcodes
`clean` for whichever band it was handed. Both bands were complete, both invocations
were legitimate, and one of them was wrong.

Here it changed nothing — the interval spans zero either way, so no verdict flipped.
That is luck, not design. Had the difference been significant, the wrong invocation
would have reported contamination where there was none, or the reverse.

### The second time a display artifact caught a logic error

The first was **three identical Brier intervals** ([[Findings & Incidents]] #46,
recorded in the development scoring). `M.A.P. vs random_walk`, `vs garch` and `vs
earnings_scaled_random_walk` all printed `[-0.00261, +0.00733]` to five decimals.
Three different baselines cannot agree to five decimals by chance, and they did not:
every baseline sets drift to zero by construction, so all three predict P(up)=0.5 and
score exactly 0.25 on every item. It was one comparison against a coin flip, printed
three times and reading as three agreeing pieces of evidence.

**Both were caught by looking at the rendered output, not by a test.** Neither is the
kind of defect a unit test finds, because in both cases every function did exactly
what it said: `leakage` differenced its arguments correctly, `compare` bootstrapped
correctly. The error was in what the arguments *meant* and how the result was
*labelled* — a layer no assertion in the suite was pointed at.

The pattern worth keeping: **an implausible-looking display is evidence about the
logic behind it.** Three identical intervals and a repeated label are both anomalies
in the output that a reader notices and a test does not. Reading your own output as
if you were a sceptical stranger is a debugging technique, not a courtesy — and it
has now found two real defects that 1,425 passing tests did not.

*Fix not applied:* both remain as reported. The orientation bug needs `_leakage` to
name its arguments by role rather than by position, and the Brier collapse is already
handled in the reporting layer. Recorded here so the next reader of that line knows
which band is which.

---

## 48 · Three near-misses in one week: fabricated data entering real artifacts, by three unrelated mechanisms

The realised-bar pin was committed on 2026-09-04. Within minutes of the commit, the
store it created held **three fabricated pins**:

```
{"ticker":"AAPL","as_of":"2026-02-02","realised_close":139.3400367105083, ...}
{"ticker":"AAPL","as_of":"2026-05-02","realised_close":131.26886939802492, ...}
{"ticker":"AAPL","as_of":"2025-02-02","realised_close":109.28935224142265, ...}
```

Those are synthetic closes from `test_cli_evaluate.py`. `PIN_STORE` was a module-level
relative path read inside `_score`, so the CLI suite — which carefully points its
ledger and `runs_dir` at `tmp_path` — wrote fixture outcomes into the real store at
`var/corpus/realised_pins.jsonl`.

**Had it survived:** AAPL's real 2026-02-02 and 2026-05-02 items would have been pinned
to values no market produced. The next real scoring would then either refuse a correct
outcome against a fixture, or — the worse branch — validate against one and report a
guard that had passed. **The guard's first act was to commit the failure it exists to
prevent.**

The narrow lesson: *"the tests use `tmp_path`"* was true of every path the command
takes as an option and false of the one added as a constant. `--pins-path` now follows
`--ledger-path` and `--runs-dir`.

### It happened again, five days later, in the same file

`map evaluate` gained `--scores-dir` for the persisted scoring record on 2026-09-09,
defaulting to `var/corpus/scores/`. The first run of the suite afterwards wrote **two
fabricated passes into the real store**:

```
var/corpus/scores/clean.dev.unpinned.dirty.json       n=1, AAPL
var/corpus/scores/clean.holdout.unpinned.dirty.json   n=2, AAPL
```

Same file, `test_cli_evaluate.py`. Same mechanism: a module-level relative default the
suite did not override — even though the suite had, by then, been carefully overriding
`--ledger-path`, `--runs-dir` and `--pins-path` for exactly this reason, with a comment
above `--pins-path` explaining why.

**One of them is named `holdout`.** A file called `clean.holdout.*.json` in the real
scoring directory, containing two AAPL rows from a fixture, in a project whose central
protection is that the holdout was spent once. It would not have survived a reading, and
the values are obviously wrong — but the same is true of the pins, and that argument did
not prevent this.

Two things worth saying plainly. First: **knowing the failure did not prevent the
failure.** The comment on `--pins-path` states the lesson in the imperative, three lines
above the place the new default should have been added, and it was not. A lesson written
next to the code is not a mechanism either.

Second, what did work: the incident surfaced within a minute because the new record is
*write-once and refuses on differing content*. The second test to write a record under
the same identity raised `ScoreRecordError` and the suite went red — 22 failures — rather
than silently accumulating fixtures. The guard designed for a different purpose (a
scoring pass that must not be regenerated casually) caught this one. The pins store,
being append-only, gave no such signal and had to be read by hand.

The narrow fix is the same as last time: `--scores-dir` now sits with the other three in
the suite's `_invoke`. The broader one is not a fix, and this entry exists to record
that: **the third instance of this will not be prevented by a fourth comment.** A test
that asserts no CLI default resolves inside a tracked or real directory would be a
mechanism. It has not been written.

### The same week, by two other routes

| # | what nearly happened | mechanism | caught by |
| --- | --- | --- | --- |
| 1 | An invented row in an AAPL track record, written for a mockup, on its way into a fixture file | **hand-authoring** — a plausible number typed to fill a layout | the author, before it landed |
| 2 | The UI's reliability fixture seeded with the project's **real** measured figures (coverage 0.78, mean PIT 0.4893) | **fixture-seeding** — realism borrowed from actual results | reversed in the same session, before the file was written |
| 3 | Fabricated fixture closes written into the real pin store | **test-suite path leakage** — a relative constant no test overrode | reading the file after the commit |

Three mechanisms with nothing in common at the implementation level: one is a person
typing, one is a design choice about fixture realism, one is a path constant. **They
are the same defect.**

Note that #2 runs the *opposite* direction — real values into a fabricated artifact —
and is no less dangerous. It is arguably worse: fabricated data in a real store is
detectable by inspection because the values are wrong, while real data in a fixture is
undetectable by inspection because the values are right. What makes it a defect is the
same thing in both directions.

### The common cause, named

**A stored value carries no marker distinguishing measured from fixture.** A float in
a JSONL file is a float. `139.3400367105083` and `94.69999694824219` are
indistinguishable as data; one came from a test helper and one from Yahoo, and nothing
in the representation says which. Every one of the three near-misses was caught by a
human noticing, which is not a mechanism.

This is the sixth-instance shape of [[Findings & Incidents]] #39 arriving in a new
place: *a representation that cannot hold the state it must distinguish.* Not "the
same field means two things" but "the field cannot express its own origin at all."

### The gap is named, and a design for it already exists

**The pipeline has provenance for runs and none for values.** It records, per run, the
code digest, the freeze digest, the model versions, the trace, the price provider and
adjustment. All of that answers *which execution produced this artifact*. None of it
answers *where did this number come from* — and the pin store, the fixtures and the
ledger all hold bare numbers.

The M.A.P. front end solves exactly this problem in a different context, and the design
is already written down and working:

- three states — `measured` (read from a real artifact), `derived` (computed from
  measured inputs), `fabricated` (from a fixture, **or derived from anything
  fabricated**);
- **weakest input wins**, so provenance cannot be laundered through arithmetic — an
  invented weight cannot become an innocent-looking target price;
- the boundary module **stamps** it, because a file that describes itself can be wrong;
- an audit with **no heuristics**: every value must be positively marked or it is a
  violation, since "skip things that look like dates" is how a real value formatted as
  `2026.07` passes unnoticed.

**This is not a proposal to build it now.** Phase 3 is the calibration correction and
this is not that. It is recorded because the third near-miss in one week is the point
at which "we keep catching it" stops being reassurance and starts being a measurement
of how often it happens — and because the candidate design is not hypothetical. It
exists, it is running, and it was written for the same failure in a context where the
consequence was a screenshot rather than a scored result.

---

## 49 · A failed development condition and a passed holdout, on samples that cannot be told apart

The pre-registered Phase 3 success condition — the corrected MAD-scale of `z`
consistent with 1.0 — **failed on development and passed on the holdout.**

| | interval | verdict |
| --- | --- | --- |
| development, corrected | [0.6997, **0.9931**] | excludes 1.0 by **0.0069** → FAIL |
| holdout, corrected | [0.8711, 1.2514] | covers 1.0 → pass |

The obvious reading is that the holdout refuted the development failure. **It did
not**, and the test that shows this was run before the interpretation was written.

The two halves are not distinguishable from each other on any dispersion statistic:

| statistic | development | holdout | difference (dev − holdout) | |
| --- | --- | --- | --- | --- |
| uncorrected calibration ratio | [0.6380, 0.8030] | [0.4967, 0.7483] | +0.0978 [−0.0584, +0.2485] | not distinguishable |
| uncorrected MAD-scale | [0.9430, 1.4173] | [1.1589, 1.6649] | −0.1645 [−0.5779, +0.1349] | not distinguishable |
| **corrected MAD-scale** | [0.7088, 1.0653] | [0.8711, 1.2514] | −0.1236 [−0.4343, +0.1014] | not distinguishable |

Intervals overlap on 54–67% of the narrower one; every difference covers zero.

**So the FAIL and the PASS are two marginal calls landing on either side of 1.0 in
samples a test cannot separate.** One excludes 1.0 by 0.0069; the other covers it.
Neither is evidence about the other, and a write-up saying "the holdout vindicated
the correction's calibration" would be reading a coin flip as a verdict.

### Why this is worth its own entry

**The error it prevents is one nobody would notice.** Every individual statement
would be true — the condition failed, the holdout passed, the correction
generalised on both primaries — and the conclusion drawn from them would be false.
There is no bug, no miscomputation, and no test that could have caught it. The only
defence is asking "are these two samples different?" before treating one as
commentary on the other.

It also compounds the earlier defect. The development verdict was already decided
by a **specification gap** rather than by the data: record 3 did not say whether
`a` and `b` are refitted inside each bootstrap resample, the refitted reading fails
and the fixed reading passes, and the gap between those readings is much larger
than the 0.0069 margin. So the FAIL half of this comparison was a judgement call,
and the PASS half is a sample the FAIL cannot be distinguished from. **Two marginal
calls, one of them made by an unspecified estimator, in samples that agree.**

The pre-registered reading still governs and is unchanged: the primary test was
corrected-versus-uncorrected on the holdout, both intervals excluded zero, and the
correction generalises. What is withdrawn is any claim that the holdout said
something about the *development condition*.

**Second near-miss this fortnight of the same shape** — a threshold that named the
statistic, the level and the direction, and still left a degree of freedom at
evaluation time. The first was ADR 0032's original A² condition, which cited the
iid 2.492 critical value for a panel with 18 clusters and had to be replaced by
record 3. The generalisable rule, recorded there and repeated here because it has
now cost twice: **a threshold is not a pre-registration unless the estimator is
also pre-registered.** The resampling scheme, what is refitted inside it, and the
null all have to be fixed, or the condition still has to be decided when it is read
— and it will be read with the answer visible.

---

## 50 · The sentence travelled further than the number

Sweeping the vault for figures superseded by the SCCO exclusions turned up something
that was not staleness. **The margin was wrong, and its direction was reversed.**

The pre-registered success condition's corrected MAD-scale interval is `[0.6997,
0.9931]` on the settled 2026-09-05 vintage. `1.0 − 0.9931 = 0.0069`. I wrote **0.0019**
— the margin belonging to the superseded `[0.6981, 0.9981]` — into the Timeline,
Findings #49, STATE.md, ADR 0033 and the README, **paired in every case with the 09-05
interval it does not belong to**. Corrected in all eight places.

### The reversal, which is the part worth recording

Reporting the re-derivation on 2026-09-04 I wrote that the margin *"tightened from
0.0069"*, and drew the inference that **"the earlier figure was partly the drifted
sample"** — that the three SCCO items had inflated the margin and removing them
sharpened it.

**The direction is backwards.** 0.0019 is the 09-04 figure and 0.0069 is 09-05, so the
margin **widened**. The interpretation was built entirely on the reversal and is
unsupported: nothing shows the drifted sample inflated anything.

**A number and a story about it do not decay at the same rate.** The number was checked
twice and corrected within a day. The sentence explaining it was quoted forward into a
report and would have gone into the vault unchallenged, because it read as a reasonable
account of a movement that never happened. An explanation is harder to falsify than the
figure it explains — it has no units, nothing recomputes it, and it survives on
plausibility.

**What the sweep suggests:** when a figure is corrected, the sentence interpreting it
must be re-derived rather than re-read. Checking that a number is right does not check
that the reason given for it is still the reason.

### The audit that found it

Twenty-four locations across five files, in four classes: eight genuine errors, five
stale figures in current-status documents, nine historical figures in narrative
sections, and two in ADRs. Only the first class was wrong when written. The rest are the
ordinary decay of a corpus that moved three times — six stale-truncation re-runs, three
`SpotDriftError` exclusions, and a re-derivation onto one pinned vintage — and they are
now marked `[superseded 2026-09-05 -> …]` rather than rewritten.

**One hypothesis in the audit was itself wrong, and is recorded because it was.** I
proposed that two published calibration intervals differed because `calibration_interval`
silently drops resamples whose ratio is undefined, and that the published figure might be
conditioned on that without saying so. Measured: **0 dropped of 2000, and 0 of 4000.**
The difference was the bootstrap draw count — 2000 in production against 4000 in an
ad-hoc script — which is Monte Carlo noise and nothing else. The vault now quotes the
production settings throughout, and the drop path is documented as existing and never
having fired on this data.

---

## 51 · A check that fails for an incidental reason is not a check that passed

Arm D of the ablation ran for two and a quarter hours and produced **one usable item
in ten**. It should never have started, and the reason it did is a category error in
how its smoke test was read.

**The smoke test failed with `InferenceStatusError` — the 12B could not load,
because arm C was running and this machine holds one model at a time (CLAUDE.md §3).
I read that as environmental, fixed the sequencing, and launched.** The fix was
correct and the inference was not: an environmental failure tells you nothing about
whether the thing under test works. **Arm D launched having never produced a single
successful item in any test.** Run in isolation, the smoke test would have hit
`ModelBudgetExhaustedError` on its first item and the arm would have been abandoned
in four minutes rather than 135.

The generalisable form, and the reason this sits with the rest of [[Findings &
Incidents]] #39: *the absence of a negative signal was substituted for the presence
of a positive one.* A check has three outcomes — passed, failed, and did not run —
and the third was collapsed into the first because the reason it did not run was
one I had already explained. **An explanation for why a check could not run is not
a result from the check.**

### What arm D actually showed

Every failure was identical in shape:

```
ModelBudgetExhaustedError — gemma-4-12b-qat generated 12000 tokens
(11997 of them reasoning) and produced no answer.  finish_reason = length
```

Three visible tokens out of twelve thousand. The single success used 9,047.

### The ceiling probe settles it: STRUCTURAL, not methodological

*Amended 2026-09-07 after the probe registered in git note record 22, which fixed
both readings in advance. This is that record's strong branch.*

Ten items at **15,000 tokens** — the largest budget the 16,384 window allows —
same prompt, same model, same everything as arm D:

```
7 x ModelBudgetExhaustedError   15,000 tokens, 14,997 reasoning, finish = length
3 x PromptTooLargeError         larger documents leave under 15,000 of headroom
```

**Ten of ten failed. Not one converged.** And the three `PromptTooLargeError` cases
mark the other edge: a 15,000 budget only fits when the document is small, so the
ceiling is not even uniformly available.

**Given every token the window physically allows, the model does not finish.** The
rejection below was written as methodological because the evidence stopped at
12,000. It is now closer to structural: there is no budget inside this window at
which the task completes, so raising the budget is not a tuning option that was
declined — it is an option that does not exist.

The methodological objections stand and are no longer load-bearing:

### The capacity claim, first rejected on measurement and then earned by it

The tempting sentence is "the model cannot fit this task in its window". **It is not
supported.** Measured on arm D's own traces: the prompt is **774 tokens** against a
**16,384** window, leaving **15,610 available**. The failures were capped at 12,000
by `max_tokens`, with **3,610 tokens of headroom unused**. The window is nowhere
near binding.

So raising the budget to ~15,000 is *physically possible*, and the refusal to do it
is **methodological, not physical**:

- it is a parameter changed after watching 12,000 fail, which is a design value
  fitted to a failure;
- and it creates differential attrition — the items that would still fail are
  exactly those needing most reasoning, so the completed set biases toward filings
  that need least, and any comparison against arm A becomes near-circular.

That is a weaker rejection than a capacity limit would have been, and it is the true
one. Whether 15,610 tokens would suffice is a **named open question**, probed
diagnostically under git note record 22 with both readings fixed in advance.

### Raising the model's context window in LM Studio: rejected on three grounds

Named so that it is rejected deliberately rather than overlooked.

1. It is a parameter changed after seeing a failure — the same objection as raising
   the budget.
2. A differently-windowed model is not comparable to arm A, which ran at 16,384.
3. **It would not help.** The window is not the constraint; `max_tokens` is. A
   774-token prompt leaves 15,610 available and the failures stopped at 12,000.
   Enlarging the window changes nothing about a budget ceiling.

### The strong result: two arms, two budgets an order of magnitude apart, one failure

This is what the ablation produced instead of a comparison, and it is worth more.

| arm | model | budget | reasoning share | outcome |
| --- | --- | --- | --- | --- |
| B | gemma-4-12b-qat | **1,000** | 997 / 1,000 = **99.7%** | no answer |
| D | gemma-4-12b-qat | **12,000** | 11,997 / 12,000 = **99.98%** | no answer |
| probe | gemma-4-12b-qat | **15,000** *(the window's ceiling)* | 14,997 / 15,000 = **99.98%** | no answer |

**A reasoning model's cost is not tunable by its budget.** Across a **fifteen-fold
range — 1,000, 12,000 and 15,000 tokens** — essentially the entire allowance went to
reasoning every time and nothing came back. The largest of the three is the most a
16,384-token window can give it. A budget cut does not shorten deliberation — it truncates the output,
which is the one part you needed.

The practical consequence for anyone building this kind of pipeline: **a reasoning
model does not drop into a fixed-budget slot.** Its cost can be reduced by removing
the agent, by choosing a model that reasons less, or by a provider-side
reasoning-effort control — which this backend does not expose. Not by giving it
less room.

The ablation set out to measure what the analyst contributes and could not, because
two of its four arms could not be made to run. That is a result about reasoning
models in pipelines rather than about this pipeline, and it cost two smoke-test
items and one abandoned arm.

---

## 52 · Removing the analyst makes the system opinionated and bullish

The ablation lost both its primaries ([[Findings & Incidents]] #51), so **A − C is
descriptive and nothing here is a causal claim.** 349 items paired, 42 blocks,
scored against the pinned 2026-09-05 snapshot.

| | arm A (full pipeline) | arm C (no analyst, 4B) | difference |
| --- | --- | --- | --- |
| CRPS | 0.03263 | 0.03707 | **−0.00444 [−0.00632, −0.00253]** |
| log score *(lower is better)* | −1.30608 | −0.85642 | **−0.44967 [−0.56655, −0.24337]** |

Arm A is better by **13.6% on CRPS**, with an interval well clear of zero.

**THREE CONFOUNDS, NAMED, AND THE DESIGN SEPARATES NONE OF THEM:**

1. **the analyst** is removed;
2. **the model** doing the forecasting changes from a 12B to a 4B;
3. **the prompt** changes, necessarily — the frozen structuralist's rule 1 is *copy
   the ESTIMATE numbers from the narrative*, and with no analyst there are none, so
   11 of 25 lines had to change.

Arm D existed to separate (1) from (2) and could not be made to run. So "the
analyst helps" is **one of three available readings** of this table and the
experiment cannot say which. It could as easily be "a 12B forecasts better than a
4B", or "the frozen prompt is better written than the one I wrote for arm C".

### The part that was not predicted, and is more interesting than the gap

| | P(up) range | median |
| --- | --- | --- |
| arm A | 0.351 – 0.631 | **0.513** |
| arm C | 0.176 – 0.819 | **0.755** |

Two things happen at once. The **span widens** — which is exactly the prediction of
[[Findings & Incidents]] #46, that the three-scenario frame compresses the
directional claim. And the centre **moves hard bullish**: a median P(up) of 0.755
against arm A's 0.513.

Arm C is not merely more opinionated. It is systematically opinionated in one
direction.

### A speculative connection, flagged as speculation

[[Findings & Incidents]] #45 records the **issuer-promotion hypothesis** — every
exhibit is an EX-99.1 earnings release, the issuer's own promotional text about its
own quarter, so a model reasoning from it should skew bullish. That hypothesis was
recorded as *untestable on this corpus*, because document type never varies and a
null has nothing to be relative to.

Arm C's bullish median is **consistent with the analyst having been buffering that
framing**, and with the buffer being removed. It is not evidence for it. The same
three confounds apply — a 4B model may simply be more suggestible than a 12B, and a
prompt asking a transcriber to forecast may invite optimism on its own. **A
correlation of one arm's median with a hypothesis nobody could test is a coincidence
until something separates them.**

What would separate them is the design already named in #45: the same tickers and
dates forecast from a document the issuer did not write. That remains a second
corpus, not a re-analysis, and this observation raises its value rather than
substituting for it.

---

## 53 · The realised-bar pin fired for the first time, and was right

`RealisedDriftError` was built during Phase 3 ([[0033-phase-3-outcome]]) for a
failure nobody had yet seen: an outcome bar changing between one scoring and the
next, with nothing to catch it. It sat unfired through the holdout spend and every
re-derivation since.

Scoring the ablation arms, it fired **six times, all SCCO**:

```
SCCO 2026-01-29   pin 186.0954   now 183.8887
SCCO 2026-04-30   pin 177.7624   now 175.6545
SCCO 2026-07-23   pin 185.0000   now 182.8063
SCCO 2025-04-26   pin  86.9669   now  85.9356
SCCO 2025-07-30   pin  91.7233   now  90.6357
SCCO 2025-10-30   pin 133.7329   now 132.1471
```

Every ratio is **1.012 to four figures** — the same split the provider applied 25
days late, which [[Findings & Incidents]] #39's sixth instance caught on the *spot*
side as `SpotDriftError`. The pin caught the identical corporate action on the
**outcome** side, which is the half that had no guard before Phase 3 and would have
scored silently.

Three details worth keeping:

- **It fired on data the guard's author did not construct.** The pins were written
  during the Phase 3 scoring, before the ablation existed, and the arms met them
  months of corpus-time later.
- **The failure was symmetric across arms.** Arms A and C each lost the same six
  items, so the pairing was unaffected and the comparison stayed at 349. A guard
  that dropped different items from different arms would have silently unbalanced
  the design.
- **It is still conservative rather than correct**, exactly as recorded in git note
  record 13: a return is scale-invariant under a split, so those six are scoreable
  once the recorded bar is rescaled by 1.012. The guard refuses because it cannot
  tell a split from a genuine revision. Split-aware handling stays on the Phase 5
  list.

**A guard that has never fired is a hypothesis about a failure.** This one is now a
measurement of one.

---

## 54 · A documentation edit suppressed a code identity it cannot affect

Writing `docs/export-contract.md` left the tree dirty. An export taken while that
file was open recorded `code.forecast_digest: null`, and the contract's own rule for
choosing between two scoring records — *prefer the one matching
`manifest.code.forecast_digest`* — could not resolve against the export shipped with
it. The document described a preference a consumer could never see work.

**The digest and the dirty flag do not cover the same thing.** `forecast_digest` is
computed over `FORECAST_ROOTS = ("config", "src/mapf")` minus everything provably
downstream of a forecast, so a prose file is outside it twice over. But
`code_version` decides dirtiness from bare `git status --porcelain` across the whole
tree, and suppresses the digest on any dirt at all:

```python
status = _git(["status", "--porcelain"], where)
dirty = bool(status)
digest = None if dirty else forecast_digest(commit, where)
```

So a README edit and an uncommitted change to `agents/` produce the same record.

**This is the 208 again, in a new place.** 208 of the clean band's forecasts carry no
digest because the tree was dirty while they ran, and ADR 0030 had to adjudicate them
as their own stratum. That was code. This is prose — and it lands in exactly the same
field, with exactly the same consequence: an artifact that cannot be pooled with its
neighbours, for a reason that in this case is not a reason at all.

### What it is not

It is not a false claim. A null digest says "unidentifiable", and on a dirty tree
that is true of the *checkout*, whatever was dirty. Nothing was overstated; something
was withheld that did not need to be.

### The narrow fix, and why it is not applied here

Scope the dirty test to the roots the digest covers: dirt inside `config/` or
`src/mapf/` suppresses it, dirt in `docs/` or the vault does not. That is narrowly
correct — the digest hashes committed content at `commit`, so it is honest precisely
when those roots match the commit, and a clean `src/mapf` with a dirty README is such
a case.

**Not applied, because it changes what future runs record and that is a
pre-registration-adjacent decision, not a tidy-up.** The current rule is
conservative in the direction the project has chosen everywhere else: over-including
costs a visible false refusal, under-including costs an invisible false claim.
Loosening it would mean a run recording a digest while *something* uncommitted was
present, and the argument that the something cannot matter is exactly the argument
ADR 0030 had to make by hand, on evidence, for 208 items.

Recorded so the next person choosing has both halves: the cost is real and recurring,
and the fix has a failure mode the current rule does not.

### The practical rule, until then

**Commit before exporting.** The export stamps the checkout it ran from, and an
export taken mid-edit ships an identity that says nothing. The same already applies
to running the corpus, and now to writing about it.

---

## 55 · A guard fired correctly, and nothing downstream ever said so

`SpotDriftError` did its job. The corpus holds a 1.012 split, and after it the anchor bar
in a later snapshot is not the bar the forecast opened on — so scoring refused SCCO's
three clean/dev items. They are the `"unscored": {"SpotDriftError": 3}` in the scoring
record, and SCCO appears nowhere among the 175 scored.

The export then published SCCO's outcomes anyway, from the same snapshot, formatted
exactly like the other 771.

**Both halves are individually correct.** Scoring refuses an item whose endpoints span
two adjustment bases. The journal is not scoring — it logs what was forecast and what the
price did, and its outcome path deliberately has no drift check, because a drift check
that suppressed a row would be the journal deciding what is worth reporting. Each is
right. The composition publishes a number that every published figure excludes, with
nothing marking it.

**This is a general shape, not an SCCO one.** A guard's output is a refusal, and a
refusal is visible only to whoever asked. Everything downstream of the refusing call sees
an ordinary absence — or, here, an ordinary presence — and no amount of care in either
component produces the marker, because neither component is wrong.

### What was built

`JournalEntry.anchor_drift`, set when the snapshot's close at the anchor disagrees with
the price the forecast recorded, beyond the tolerance scoring itself uses. The tolerance
moved from `scorer` to `window` so both read one constant; the journal cannot import
`scorer` without reaching the scoring machinery its contract forbids.

Nine of 779 runs carry it: seven SCCO at ×0.988142 and two AAPL at ×1.007509.

**Marked, not excluded.** An outcome that exists and is not comparable is a different
fact from an outcome that does not exist, and the four-value `outcome_status` discipline
says never omit a row. The marker is what stops the two from looking identical.

**Named for the drift, not for the refusal.** Six of the nine are ledger items; one is a
repeat and two are outside the corpus, and no scoring pass ever attempted those three. A
field called "scoring declined this" would be false for a third of the cases it covers.
The drift is a fact about the price series; what scoring does about it is a consequence,
stated in the sentence a UI shows rather than in the field name.

### What is still not covered

The realised bar has the same exposure and no marker. `RealisedDriftError` pins the
outcome at first scoring, and the pins live in `mapf.corpus` — above `mapf.eval` — so the
journal cannot read them without breaking the layer contract. The export's outcome is
honestly labelled with the snapshot it came from, which is weaker than a comparison
against the pin and is what there is. Recorded here rather than left to be rediscovered.

---

## 56 · The longest window is not the most recent one

`map export` picked each company's price series with "the window covering the widest
span". Every window in the scoring vintage is about 764 days, so span was effectively a
tie across all candidates and the winner was whichever the filesystem happened to yield
first.

**92 of 120 charts ended before data the same vintage held** — median 273 days behind,
maximum 551. **296 of 779 runs had an anchor date past the end of their own company's
chart**, so a run marker could not be placed on 38% of them. ZTS is the clearest: the
export shipped `2023-02-15 .. 2025-03-20` while `2024-08-07 .. 2026-09-10` sat in the
same directory, covering the run and reaching seventeen months further forward.

Nothing was missing and no vintage was wrong. All 120 tickers had windows; the selection
read the wrong field.

Selecting on **latest end date, span only as a tie-break**, takes anchors-off-chart from
296 to **0** and costs nothing: the latest-ending window is a full 764 days in every one
of the 92 cases, so no chart got shorter. Confined to `_widest`; `covering()` and the
outcome path are untouched, and outcomes were never affected — they require a window that
*spans* the anchor, which is a different question and a different call.

The residual 32 charts whose last bar precedes the vintage's latest window *boundary* are
an artifact of comparing a bar date to a requested end date six days in the future. Every
bar the vintage holds is exported.

### A derived ratio is not an identifier — noted 2026-09-10

The `anchor_drift.ratio` above is computed per run from that run's own recorded spot,
and both sides are float32 as the provider served them. So nine drifted rows carry
**seven distinct values** for **two** corporate actions:

```
SCCO  0.9881423249262894  0.9881423325818092  0.9881423105034546
      0.9881422964658348  0.9881422790266337  0.9881422904830778
AAPL  1.007508703480546  (both rows)
```

Found by a consumer reading the exported files, not by the code that wrote them, and
that is the general point: **a quantity computed to describe an event is not a key for
the event.** Two runs of the same split produce ratios that differ in the ninth decimal
because their anchors differ, and a consumer grouping on equality gets one group per run.
The contract now says to group on `ticker` or round to six places.

Nothing is wrong with the value — it is the honest ratio for that run. The error would
have been in a reader treating it as an identity. Same family as the `head_tail_v1`
entry in #39, from the other direction: there one name covered two states, here one state
produced seven names.

---

## 57 · A pre-registered measure, reported five times, and never as a number

Git note record 14 fixed the holdout report before the spend: a primary test, seven
secondary measures, and **"EVERY ITEM ON THE LIST IS REPORTED, IN THE ORDER GIVEN,
WHATEVER IT SAYS."** One of the seven was

```
S5  corrected and uncorrected against all three baselines -- random walk, GARCH,
    earnings-scaled random walk -- on CRPS and log score
```

— twelve comparisons: two forecasts, three baselines, two rules.

**What survives of S5 is one sentence.** It appears in five documents, all written on
2026-09-05 after the spend (ea47f4b): ADR 0033, STATE.md and Timeline §16 (5ada5aa), that
commit's own message, and the README's Phase 3 section (a75d156).

> Corrected, the system beats the earnings-scaled random walk on CRPS — up from
> indistinguishable — and still loses to GARCH and the plain random walk on both rules.

The Timeline alone adds *"as it did uncorrected"*. No figure and no interval for S5 exist
anywhere. Every neighbouring measure does have them: P1 and P2, S1 to S3, S4's tilt and
Anderson–Darling statistic, S6 and S7 all have figures in Timeline §16. S5 is the one
reported in words only.

### What the sentence does not say

Of the twelve comparisons:

- **two are not stated at all** — both forecasts against the earnings-scaled random walk
  on the log score;
- **four rest on "as it did uncorrected"**, in one of the five documents — the uncorrected
  forecast against GARCH and the plain random walk, on both rules;
- one is stated by implication — uncorrected against the earnings-scaled random walk on
  CRPS, via "up from indistinguishable";
- five are stated outright, as a verb.

**And none says what "loses" means.** The evaluator writes a comparison in exactly one of
two forms (`eval/aggregate.py`): a significant one as `worse by 5.4% [+0.00071, +0.00278]`,
anything else as `indistinguishable at n=175 … interval spans zero — this is not evidence
of no difference`. The distance between those forms is the whole content of the result.
On development, M.A.P. against GARCH on CRPS came out *indistinguishable*,
`[-0.00035, +0.00220]`. "Loses" on the holdout could be either form. Record 14 committed to
reporting S5 whatever it said, and what survives does not say what it said.

### Why it cannot be recovered

- The holdout's per-item scores were never persisted, and `map evaluate --split holdout`
  refuses before computing anything once the spend is recorded (ADR 0031). No re-run exists
  that does not defeat the guard.
- `corpus/holdout_spend.jsonl` holds what ADR 0031 specified — date, band, item count,
  commit, digests, calibration — and no results. ADR 0031 said nothing either way about
  keeping them.
- The scoring-record store (83370f6) arrived on 2026-09-09, four days after the spend. The
  development summaries now in the export were produced by re-scoring development, which is
  re-scoreable. Nothing did the same for a sample that cannot be scored twice.
- The printed output is not in any retained session transcript.

The gap is permanent, and it is a gap in the report, not in the holdout: the spend was
single and clean, and the primary result stands on figures with intervals.

### What is and is not affected

- **The Phase 3 result is untouched.** P1 and P2 are figures: log score −0.28778
  [−0.45255, −0.11117], CRPS −0.00090 [−0.00178, −0.00012].
- **The development comparison is intact and exported** — `scores/clean.dev.*` carries all
  six comparisons — three baselines on each rule — with intervals, and on its own supports "does not beat a
  plain random walk or GARCH" for the development companies.
- **What cannot be checked** is that the same held on the holdout, and the one improvement
  the sentence reports — corrected against the earnings-scaled random walk on CRPS — which
  rests on nothing but the sentence. The front end's door therefore says "on the
  development companies", the version every figure behind it is in an exported file for.

Found 2026-09-17, checking a front-page claim against the export before it shipped — not
by re-reading the Phase 3 write-up, where the sentence reads as a summary of rows that
were simply not tabled.

### The shape

Same family as #50 — the sentence travelled further than the number — with nothing left at
the other end. There, a correct figure was restated wrongly and the story about it outlived
the correction; #50's rule was to re-derive the sentence when the figure changes. Here
there is no figure to re-derive from.

**A pre-registration that fixes *what* is reported without fixing *its form* can be
satisfied by a sentence.** Record 14 required every item reported whatever it said. It did
not say *as figures with their intervals*, and a sentence meets that letter while dropping
the one distinction the evaluator exists to make. Reporting it beside tables for every
neighbouring measure is what made the gap invisible: the section looks complete.

**The practical rule:** for a sample that cannot be scored again, a pre-registered measure
is reported when its figures are in a tracked artifact — the spend record or a committed
report — and prose about it is written after that, from it. For a re-scoreable split the
scoring-record store now does this by construction. For a one-shot sample nothing did.

---

## 58 · The spend record names a commit the published history does not contain

`corpus/holdout_spend.jsonl` records that the holdout was scored at commit
`9cb1b84f2172…`. **That commit is on no branch.** The published history carries
`710879a` in its place — same author date, same message, a different tree.

**What happened.** On 2026-09-08 a `git pull --rebase origin main` picked up two
commits made in GitHub's web interface and replayed 25 local commits on top of them.
Author dates survived, committer dates moved to 09-08, and all 25 got new SHAs —
including the one HEAD pointed at when the holdout was spent three days earlier.

**Nothing about the spend itself is in doubt.** The record's `forecast_digest` is
`null`, which says the tree was dirty when the holdout was scored, so that commit never
identified the code that ran. The band, the item count, the freeze version and digest,
the date and the price vintage all stand, and the primary results are figures with
intervals. What lapsed is the ability to resolve one field of the record. (#57 is the
separate question of what the holdout report does not carry at all.)

**A rebase is a rewrite.** Nothing warned, and nothing checks: a field naming a commit
is a claim about a history that any later rebase can move underneath it, silently. The
durable form is to write the SHA down only once the history holding it is published —
or to pin it, as below.

### What the originals were hanging from

Only this machine's reflog. They were never pushed, and unreachable objects are
prunable by any `git gc` roughly 30 days after they fall out of a ref — here from about
2026-10-08. Found on 2026-09-17, nine days into that window, while scoping an unrelated
history rewrite.

- **`refs/archive/pre-rebase-2026-09-08`** pins `5fe46e0`, the pre-rebase tip, which
  holds all 25 originals including `9cb1b84`. Reachable means gc cannot take them.
- **`~/Desktop/repo-bundles/M.A.P.-2026-09-17.bundle`** is a `--all` bundle, verified
  as a complete history and test-restored: `9cb1b84` comes back carrying its original
  `2026-09-05 05:23:25` committer date. map-ui has one beside it.

### The rule that follows

**Any history rewrite must exclude `refs/archive/*`.** A rewrite walks every ref, so
including the archive rewrites the very commits it exists to preserve and leaves the pin
holding copies under new SHAs — the one thing it is there not to do. The bundles are the
second line, and they sit outside the repository for the same reason.
\n
---

## 59 · A guard that was audited, deferred, and then fired exactly as written

`map evaluate --band ambiguous --split dev --check` refused with **"5 distinct
forecast digests produced this band"**, listing 208 runs from a dirty tree with no
digest at all. On that report I told the operator the ambiguous band could not be
scored without `--allow-mixed-code` — an override whose own help says it *records a
judgement* that the differing files cannot change a forecast, the adjudication
[[decisions/0030-code-boundary-adjudication|ADR 0030]] performed for the clean band.

**Every one of those digests belongs to the clean band.** Counted per population:

| Population | Runs | Distinct digests |
| --- | --- | --- |
| ambiguous / dev | 177 | **1** |
| ambiguous / holdout | 173 | **1** |
| clean / dev | 178 | 4, including **106 dirty** |
| clean / holdout | 173 | 5, including **102 dirty** |

The ambiguous band is uniform — one digest across all 350 runs — and needs no
judgement at all.

**This was known.** `_code_versions` iterates `ledger.resolved()` with no band and no
split while printing "this band", and the function two above it, `_freeze_versions`,
carries the comment *"Band-filtered, unlike `_code_versions` below — which is audit
finding #4 and is deferred, not overlooked."* The [[Guard Audit]] wrote it down in
the abstract: *"an ambiguous-band commit can refuse a clean-band score."* It fired
in the mirror image, and [[decisions/0022-guard-scope|ADR 0022]] §4 lists it as a
known limitation.

### What the deferral cost

Nothing in the data, and one wrong report. A deferred finding does not stay
theoretical: it waits for the first operator who does not know it is there, and then
it reads as evidence. The refusal was printed by the project's own guard, in the
project's own words, naming a population it had not measured — so the natural
reading was that the ambiguous band needed an ADR-level judgement, and the natural
next step was to make one.

**The operator caught it by arithmetic**: the digest table summed to 701, which is
every panel run in the corpus, against 177 items in the population being scored. The
sum was in my own report, and I had not added it up.

### The fix, and why a band filter would have been the wrong one

Scoped to **the populations the pass scores**, not to the primary band. Too broad
refuses on runs the pass never reads, which is this bug. Too narrow is worse:
`_leakage` scores the other band at the same split as part of the pass, so a
band-scoped guard would have let the clean band's 208 dirty runs through with
nothing recorded — the guard silent on runs that were scored. Both directions are
tested. `--no-leakage` narrows the pass to one population, and the guard narrows
with it.

The printed line now names the population its count describes: `digest
cccccccccccc (1 runs in ambiguous/dev)`, or `produced ambiguous/dev and clean/dev`
when the leakage estimate brings the second one in. A count that names its own
population cannot be read as a different one.

### The shape

Same family as [[#50]] — the sentence outliving the number — from the other end. There
the story about a figure went stale; here the figure was never about what its sentence
said, and the sentence was in the code. A docstring is not a scope, and a guard that
prints a population it did not filter on will eventually be believed.

---

## 60 · A test suite that passed twenty-three hours a day

Two tests asserted `date.today().isoformat()` against values the code stamps with
`datetime.now(UTC).date()`. The machine runs on BST, so the local date and the UTC date
disagree between midnight and 01:00. At 00:03 on 2026-09-26 both failed:

```
tests/unit/test_cli_export.py  manifest["exported_at"]     '2026-09-25' == '2026-09-26'
tests/unit/test_cli_runs.py    outcome["retrieved_on"]     '2026-09-25' == '2026-09-26'
```

**The code was right and the tests were wrong.** `exported_at` and `retrieved_on` are
vintage stamps; a stamp that depends on the exporter's timezone is a stamp two people
reading the same artifact would disagree about. UTC is the correct choice and it is made
consistently — `export.py:415` and `runs.py:246` both call `datetime.now(UTC).date()`.
The assertions simply reached for the wrong clock.

### Why it had survived

It is invisible for most of the year and most of the day. During GMT the two clocks
agree and the tests cannot fail at all; during BST there is a one-hour window, and
nobody had run the suite inside it. The failure needs a timezone, a season and an hour
to coincide, which is exactly the shape of a bug that sits in a repository indefinitely
and then fires on the day it is least welcome.

### Why it mattered on this particular day

The working agreement had changed that morning: **push after every commit, provided both
suites pass.** A suite with an hour-long dead zone in it turns that rule into "push
after every commit except between midnight and one", which nobody would have written
down and nobody would have remembered. A flaky gate is worse than a slow one, because it
trains you to push past it.

### The general shape

**A test that constructs an expected value must construct it the way the code does.**
`date.today()` and `datetime.now(UTC).date()` are the same value 96% of the time, which
is the worst possible hit rate: often enough to look correct, rare enough that the
failure arrives with no recent change to blame. The same applies to any clock, locale or
default that the test and the code each reach for independently.

Related to [[#55]] in kind rather than in subject: two halves individually correct, and
a composition that is not.

---

## 61 · A recorded verdict recomputes from its pre-registration; the code that produced it does not survive

The Phase 2 ambiguous-band replication of the tail excess came back **PARTIAL**: the
exceedance counts replicated emphatically, the tail ratio's interval did not clear 1.0.
`24fbedc` (2026-09-04 19:50) recorded it with its numbers — *"the tail ratio did not (CI
[0.9945, 1.5365], missing the registered threshold by 0.0055)"*. The Phase 3 write-up
deleted those three lines from [[STATE]] the next day. The rounded margin has been in the
README since 2026-09-05.

**The statistic was recomputed from the pre-registration in 2026-09, four weeks later, and
returns the same verdict.** Not from the original script: that does not exist anywhere.

### What survived and what did not

The **result** was committed and then removed. The **code** never was. `git log --all -S`
finds no commit on any ref containing `mad_scale`, `tail_ratio`, `1.4826`,
`median_abs_deviation` or `MAD_TO_SIGMA`; the only near-match is `tails_heavy`, a boolean
on `PitTest`. No session transcript covers it either — they span 2026-08-28 onward, but
none spans 2026-09-04 after 15:00, and the result was committed at 19:50. So the script
that produced `[0.9945, 1.5365]` is gone, and the number was recoverable only because it
had been written into a tracked file before being deleted from one.

### What the recomputation establishes, stated exactly

Records 2 and 4 fix the statistic as `RMS(z) / MAD-scale(z)` with a cluster-robust 95% CI
from the moving-block bootstrap, 4,000 draws, seed 20260813, ten-day blocks. Rebuilt from
that alone, against `block_resamples`:

| band | recorded | recomputed | n then / now |
| --- | --- | --- | --- |
| development | `[1.0135, 1.4372]`, excludes 1.0 | `[1.0169, 1.4368]`, excludes 1.0 | 178 / 175 |
| ambiguous | `[0.9945, 1.5365]`, misses by 0.0055 | `[0.9947, 1.6078]`, misses by 0.0053 | 177 / 174 |
| ambiguous, rebuilt | `[0.9945, 1.5365]` | `[0.9933, 1.5378]` | 177 / **177** |

**The verdict is the same on both bands, and the same under every reading the
pre-registration left open.** On the ambiguous band as persisted, the lower bound — the
one the verdict turns on — is within **0.0002**, while the upper is **0.07 apart**. The
development band, differing by the same three items, lands within 0.0034 on both bounds.

### The three missing items, and what they turned out to be

The first explanation offered for that upper bound was a dropped extreme, and it was
wrong: the count past three sigma is **8 on both 177 and 174**, so none of the three was
in the tail at all.

They are all **SCCO**, at three different anchors, each refused with a drift of exactly
**1.19%**. One uniform re-adjustment of the whole series, not three independent
disagreements — the SCCO stratum record 13 set aside.

A uniform factor scales both endpoints of a return, so the return is unchanged, and the
original basis is still on disk in two places: the anchor is the forecast's own recorded
`spot_price`, and the outcome is the realised-bar pin taken at first scoring. Rebuilding
the three from those and recomputing on the full 177:

| | return on the original basis | off today's re-adjusted series | z |
| --- | --- | --- | --- |
| SCCO 2025-04-26 | −0.035945 | −0.035945 | −0.95 |
| SCCO 2025-07-30 | +0.048822 | +0.048822 | +1.27 |
| SCCO 2025-10-30 | −0.020697 | −0.020697 | −0.68 |

The two routes agree to **1e-8**, which is the check that makes this a reproduction rather
than a new measurement: had the re-adjustment fallen inside any of the three windows the
columns would differ, and the rebuild would not be admissible.

**It closes the gap.** On 177 the interval is `[0.9933, 1.5378]` against the recorded
`[0.9945, 1.5365]` — **0.0012 on the lower bound and 0.0013 on the upper**. Both bands now
reproduce on both bounds.

And the mechanism is the opposite of the one first proposed. The three are ordinary body
items, z of −0.95, +1.27 and −0.68. Removing them does not touch the numerator's tail; it
moves the **denominator**, the MAD-scale, from 1.1541 to 1.1455, which lifts the ratio from
1.2346 to 1.2493 and carries the whole bootstrap distribution with it. A tail ratio is
sensitive to its body, and three unremarkable items were enough to move the upper bound by
0.07 while leaving the lower one — and so the verdict — where it was.

This is a reproduction check and nothing more. The persisted 174-item record remains the
re-derivable population, and the headline figures stay stated on it.

**The development row covers the resampling on a band that was never disturbed.** Record 4
Part A is the only place a tail-ratio *interval* is recorded for a band this repository can
still score straight from its persisted record, so it exercises the bootstrap without any
reconstruction. Its baselines' intervals cannot be checked: the scoring record carries
baseline CRPS, log score and Brier, but no baseline sigma.

**The statistic itself is pinned separately**, against figures the pre-registration does
not contain: ADR 0032's MAD-scale `1.0864` and tail ratio `1.2267` reproduce to four
decimals on the development record, and record 4 Part A's counts and block spreads —
11 in 7 blocks, 7 in 5 blocks, 2 past four sigma — reproduce exactly.

### The wrong resampler gave the opposite answer

A first attempt binned days as `day_index // 10` — non-overlapping blocks — and returned
`[1.0062, 1.5836]`, **excluding 1.0** and so pointing at replication where the record says
partial. That is a **different estimator**, not a failed reproduction: `block_resamples`
draws overlapping windows anchored on occupied days and truncates to n. The disagreement is
what located the right one, and the number is recorded here so it cannot later be mistaken
for a second opinion about the same test.

### The open choice, and why it does not matter here

The pre-registration fixed the statistic, the draws, the seed and the block length. It did
not fix the interval construction or where the MAD is centred. Measured on the ambiguous
band: percentile misses the bar by 0.0053, the basic interval by 0.1091, and centring the
MAD on zero instead of the median by 0.0459. **All three cover 1.0**, so no reading reaches
a different verdict. Centring is settled by the record anyway — median-centring is what
reproduces ADR 0032's 1.0864, and zero-centring gives 1.0911.

Worth noting that the two constructions nearly coincide on development
(`[1.0169, 1.4368]` against `[1.0165, 1.4364]`) and diverge on the ambiguous band
(`0.9947` against `0.8909`). The ambiguous bootstrap distribution is skewed where the
development one is not, which is consistent with the four items past four sigma it carries
against development's two.

### The shape

Same family as [[#57]] — a pre-registered measure whose figures were never persisted — but
with the opposite outcome, and the difference says which part of the practice worked.
There, the pre-registration fixed *what* to report without fixing its *form*, and a
sentence satisfied it with nothing behind it. Here the pre-registration fixed the
**estimator**: the statistic, the resampler, the draws, the seed and the block length. That
was enough to rebuild the test from a git note four weeks later and land within 0.0002 of
the bound the verdict turns on.

**The practical rule:** a pre-registration that names its estimator precisely enough to be
re-implemented is worth more than the script that first ran it, and costs four extra lines
to write. What was avoidable was the other half — a statistic reported in a write-up and
implemented only in a scratch file has no way back, and deleting the write-up's own lines
in the next commit nearly closed that route too. The statistic now lives in
`mapf.eval.aggregate` with tests, which is where it should have been on 2026-09-04.

---

## 62 · A test isolated on six paths out of seven, and the seventh was the one nothing read

`map export --check` re-derives the identity of every input and names the ones that have
moved. Its test helper passed `--out`, `--frozen`, `--ledger-path`, `--filers-path`,
`--snapshot` and `--config`, all pointed at `tmp_path`. It did not pass `--runs-dir`, which
therefore defaulted to `Path("runs")` — **the repository's own 826 run directories**, read
from whatever the working directory happened to be.

The tests passed. `test_check_reports_a_current_export_as_current` asserted "nothing has
moved" and got it; `test_check_names_the_input_that_moved` asserted "1 of 7 inputs have
moved" and got that too.

**They passed because nothing read the unisolated path.** The seven identities were the
freeze version and digest, the code commit and forecast digest, the ledger count, the
symbol vintage and the price snapshot. Not one of them touched `runs/`. The helper was
handing the command a path into the real repository on every invocation, and the defect was
undetectable by construction: an input nobody reads cannot disagree with anything.

It surfaced the moment run counts joined the comparison for ADR 0036 §5 — at which point
the pre-existing tests began reporting the repository's 779 unknown-source runs against a
fixture export's zero, and failed. **The new feature did not break them. It made them
capable of failing.**

### The family

[[#39]] collected six representations that could not hold the state they had to
distinguish, and one of its six rows is this same command: *the `--check` stale line —
"nothing is stale" versus "the check never ran" — prints only when the list is non-empty,
so a clean report and a silently skipped one are the same output*.

This is that shape moved one level out, from the code into the test. There the two states
collapsed because the output had no encoding for the difference. Here they collapsed because
the assertion had no *dependency* on the difference: "isolated from the repository" and "not
isolated, but reading nothing" produce identical test output, for as long as the reading
part stays true.

**So a test's isolation is not a property of the test.** It is a property of the pair — what
the test isolates and what the code reads — and only one half of that pair is visible when
the test is written. This helper was correct on the day it was written and became wrong
without being edited.

### The practical rule

**Isolate every path a command accepts, not every path it currently reads.** The cost is one
argument; the cost of the alternative is a test that silently widens its blast radius the
next time the command grows. `_export` in the same file already did this — it passed
`--runs-dir` from the beginning — which is why the export tests were unaffected and only the
`--check` tests broke. One helper had the habit and the other did not, and the difference was
invisible for as long as it did not matter.

Not caught by review, and it would not have been: reading `_check` beside `_export` shows one
argument missing from a list of six, and the reason it is missing is a fact about a different
file. The thing that found it was adding a reader.

---

## 63 · A test double that stopped matching, and wrote to the real journal

Screenshots of the live-analysis result are taken by intercepting `POST /analyze` in
Playwright and fulfilling it from a recorded stream, so that a picture costs no run. In
the same batch of work the endpoint was renamed `/analyse`, for spelling consistency
across the URL and the labels. The intercept pattern was not renamed with it.

Playwright does not warn about a route that matches nothing. The request went past the
stub to the live server, which ran the pipeline for real and wrote **a second permanent
entry to the run journal**.

**It cost no inference.** All three agents were cache hits — same document, same prompts,
same sampling — and the run completed in four milliseconds. That is why it was invisible:
the script finished in its usual time and produced a screenshot that looked right. The
only trace was a run count one higher than it should have been, and a set of prices that
had moved.

### Why the route fix is not the fix

Renaming the pattern repairs this rename. It does nothing about the next one, and the
failure mode is not specific to renaming: **an intercept that stops matching fails open.**
The stub's whole job is to stand between a screenshot and a side effect, and its failure
gives no signal at all — the request simply proceeds to the thing it was meant to prevent.

Same family as [[#62]], one level further out. There, a test helper passed six paths into
a temporary directory and a seventh into the repository, and nothing noticed for as long
as nothing read the seventh. Here, a stub covers one route and the real server is reachable
on all of them; nothing notices for as long as the pattern happens to match. **Both are
isolation that holds by coincidence rather than by construction**, and in both cases the
coincidence was invisible in the code that depended on it.

### The repair

The screenshot server runs against `FakeProvider` and a temporary runs directory. Then a
missed intercept produces a fixture-backed answer written somewhere that is deleted
afterwards, and the worst outcome is a wrong picture rather than a permanent record.

*(2026-09-30: half of this is wrong — there are no fixtures, so a missed intercept gets a
refusal, not an answer. See #69.)*

The principle: **when a double exists to prevent a side effect, remove the side effect from
the environment as well as intercepting the call.** An intercept is a claim about what a
request will do; an environment with nothing to damage is a fact about what it can do. The
first can stop being true without anybody editing it.

### On the entry itself

It stays. It is a real run of real code over a real document, and the journal is a record
of what happened rather than of what was intended — the same reason a dirty-tree scoring
record was kept beside its clean twin rather than deleted. Both KO runs are counted, the
door says `2 live runs`, and this note is why the second one exists.

---

## 64 · A price that said "close" and was a live quote

The first live run anchored KO at **87.33**. The second, made the next morning on
the same document, anchored at **87.18**. Both manifests record
`last_trading_date: 2026-09-28`. Both forecasts carry the number in a field called
`spot_price`, which ADR 0012 defines as the close a forecast is scored against.

The first run was made at **15:52 in New York — eight minutes before the bell.**

A price provider returns a daily bar for the session in progress and keeps
updating it. It has the same shape as a settled bar, the same fields, and a
`close` that is simply the last trade so far. `PriceWindow.last_close` takes
`bars[-1].close`, so a run made during market hours anchors on a live quote while
every artifact around it says close.

**The 0.15 gap is not the point; the label is.** The scenarios on that run span
2%, so a 0.17% error in the anchor changes nothing anyone would notice. What it
changes is what the record means: `spot_price` is the number every later
comparison is measured from, and `SpotDriftError` exists precisely to refuse a
scoring run whose recorded spot has moved from the series by more than 1e-4
relative. An intraday anchor **is** that drift, present from the moment the
forecast was written, and the guard cannot see it because the guard compares the
recorded spot against the series the forecast itself was produced from.

### It reached a public page before it was caught

The hosted replay had just been built, pinned to that run, and the result head
read *"anchored 2026-09-28 · at that day's close"* — a false statement about a
real company's price, on a page meant for people who cannot run the models and
therefore cannot check.

Three reviews of that screen did not catch it. It was found by asking why two runs
of the same document anchored at different prices, which is a question about the
data rather than about the code.

### The repair, in two halves

**Forward:** `settled_window` drops a bar whose session has not closed, judged on
the exchange's own clock — 16:00 America/New_York, via `zoneinfo` rather than a
fixed offset, because a fixed offset is wrong for five months a year and fails in
a way that only appears twice. A window with nothing but an unfinished session
refuses rather than anchoring.

**Backward:** the two runs are not edited. They are a record of what happened, and
editing a run to make a later page truthful would be the wrong repair to the wrong
artifact. Instead `map export` works out what the price actually was, from the
run's own recorded instant, and writes `price_kind` and `price_taken_at` beside
it. The page now reads *"price taken during that session, 19:52 UTC — not a
close."*

### The shape

**An artifact can be internally consistent and still describe something that did
not happen.** Nothing in either run contradicts anything else in it. The manifest,
the forecast and the trace all agree, and they agree on a wrong thing, because
they all inherited it from one upstream read that nobody thought to question.
`fetched_on` in [[#39]] was the same shape: 701 manifests carrying a date on which
no price was ever fetched, consistent everywhere, false everywhere.

**The practical rule:** a value copied from a provider is a claim about the
provider's state at a moment, and a moment is part of the value. Where the claim
is "this is a close", the check is not on the number — it is on whether the thing
that produces closes had finished producing that one.

### Addendum — two more, and they were already labelled wrong

Two AAPL runs anchored 2026-08-13 (`46cf0ac0`, `d8da0ae6`) were shown on every screen
as **re-based by a corporate action**, factor ×1.007509. None of that fit. A 0.75%
factor is not a split and is several times Apple's quarterly dividend; a real
adjustment re-bases every earlier close, yet AAPL's panel runs and even its
2026-08-11 runs showed no drift; and the two runs shared one spot, 302.985.

They were made at **13:02 and 13:11 New York time** — mid-session, nine minutes
apart, off the same unfinished bar. The settled close was 305.26. This is the same
defect as the KO run above, found two weeks earlier, and explained away by the
screens as something else.

**The explaining-away is the part worth recording.** The export carried a ratio and
nothing else, and every screen that met a ratio supplied a cause for it: the drift
panel's title, its per-group label, the chart legend, the journal's detail heading
and the disclosure all said "re-based" or "corporate action". Nothing had recorded
the cause, so each screen inferred the only one it knew. The inference was right for
SCCO and wrong for AAPL, and the two looked identical because the screens were
reading the same field.

The journal now decides `price_kind` for every run from what the run recorded, and
each drift carries a `cause` from it: **three runs are `intraday`** — the two AAPL
runs and KO `b8748710` — and every other run on disk, all 701 corpus items included,
is a settled `close`. SCCO's seven stay a corporate action. The rule reads
`fetched_on` before `as_of`, because corpus runs carry a synthetic `as_of` at 00:00
UTC on the bar's own date — the evening before that session opened — and a rule that
compared `as_of` with the anchor session, which the replay briefly used, would have
labelled all 701 of them intraday.

The settle time is now **16:30 New York**, not the 16:00 bell: the closing auction
sets the official close and a provider's bar can keep moving for minutes after it.

---

## 65 · An architecture contract broken, and no gate that could see it

The fix for #64 put the session rule in `mapf.data` and imported it from
`mapf.pipeline.run`. ADR 0004's contracts forbid exactly that — pipeline never
imports adapters — and, transitively through `run.py`, corpus selection too. Two of
seven contracts were broken on `main` for one commit.

**Nothing ran them.** `lint-imports` is listed in `docs/setup.md` as a gate, and the
definition-of-done test says linters are kept out of pytest deliberately because they
run "in the same command that runs this suite" — in CI. There is no CI in this
repository. The test asserts only that the contracts are *configured*. The push gate
in practice was pytest and the node suite, and neither can see an import graph.

Found while adding `price_kind` to the journal, which needed the same rule and is
forbidden from importing `mapf.data` for the same reason. The rule is pure — the
standard library's `zoneinfo` and nothing else — and now lives in `mapf.core`, where
every layer may import it and "core is a sink" still holds. All seven contracts kept.

Same family as [[#62]] and [[#63]]: **a check that exists and does not bind.** #62 was
a test isolated on six paths of seven; #63 a stub covering one route of many; this is
a gate documented as enforced by a runner that does not exist. In each case the
safeguard was real, and what was missing was anything that made it run.

**Open, and not decided here:** whether to add a CI workflow, or run `lint-imports`
from inside pytest against the recorded reasoning in `test_definition_of_done.py`.
Until one of those happens, the contracts hold only because they are run by hand
before each push.

**Resolved 2026-09-29:** CI, on every push, running the whole gate (ADR 0037). The hand-run
gate stays, and now includes ruff and mypy, which had let 47 errors reach `main` the same
way. Setting it up found a further class the hand-run gate cannot see (#67).

---

## 66 · The one finding that replicated kept its verdict and lost its numbers

The Phase 2 close recorded the second-band replication of volatility compression in the
vault's STATE file, `M.A.P.-vault/STATE.md` at `852b1cb` (2026-09-04 19:50; pre-rebase twin
`24fbedc`):

> **Volatility compression — REPLICATES, fully, against both baselines.** S1 corrected
> slope 0.409 (RW) / 0.327 (GARCH), both Frisch intervals excluding 1.0; S2 spread
> ratios 0.516 / 0.468; S3 negative and monotone at all three cut depths.

The Phase 3 write-up, `5ada5aa` (2026-09-05 09:44), replaced that with *"Volatility
compression replicated out of sample against both baselines (record 6)"*: the verdict
without a figure. It is the same commit that removed the tails interval (#61). The
Timeline's re-derivation on the 2026-09-05 vintage says "compression still replicated" and
gives no number either. So the figures of the one finding the write-ups call established out
of sample were in a tracked file for fourteen hours, and have been only in history since.
**No bound was ever recorded.** "Both Frisch intervals excluding 1.0" is all there is.

**Recomputed from the registration on 2026-09-29. The recorded figures reproduce.**

### What survived and what did not

As in #61, the result was committed and removed and the code never was. `git log --all
-S Frisch` finds the git notes and the vault commits that recorded and removed it, and
nothing under `src/` or `tests/` on any ref. The estimator is rebuildable from the notes on `ad71b13`
alone: record 6 for S2, record 8 Part B for S1, record 9 for how to read it. Forward slope
of log σ(M.A.P.) on log σ(baseline); reverse slope; λ = corr(log σ_RW, log σ_GARCH) on the
band itself; corrected slope = forward / λ; Frisch bounds [forward, 1/reverse]; cluster-robust
intervals on ten-day blocks, 4,000 draws, seed 20260813. The replication criterion is the
random walk's widest interval, the forward slope's lower bound to the inverse reverse
slope's upper, excluding 1.0. It is now `mapf.eval.compression`, committed with its tests
before any figure below was written down (`0695e5b`).

### The inputs, and why the original samples are exact rather than reconstructed

σ(M.A.P.) is persisted and the baselines' σ is not. Each item's σ(M.A.P.) is `simulate()`
over its forecast's scenarios, and it matches the persisted `map_sigma` with a relative gap
of exactly zero on every item the scoring records hold. The baselines' σ were refit with
`random_walk` and `garch` on each item's prior window from the pinned 2026-09-05 snapshot,
which is the scorer's own path.

Both samples are the originals: 178 development items and 177 ambiguous. Today's scoring
records hold 175 and 174. The three missing from each band are all SCCO, refused since the
split Yahoo applied late (record 13). A uniform factor leaves log returns unchanged, and σ
is built from nothing else, so these items' σ are the same before and after it. The
development row below confirms that: every figure record 8 lists reproduces from today's
snapshot.

### Development, against record 8 (178 items, 18 occupied blocks)

| | random walk | GARCH |
| --- | --- | --- |
| forward | 0.3166 [0.2609, 0.3811] | 0.2119 [0.1375, 0.2933] |
| 1 / reverse | 0.8102 [0.6548, 0.9993] | 0.9796 [0.8014, 1.2348] |
| corrected | 0.3765 [0.3144, 0.4659] | 0.2520 [0.1656, 0.3423] |
| λ | 0.8410 | 0.8410 |
| spread ratio | 0.5065 | 0.4556 |

**Every point and every bound matches record 8 to four decimals.** That is the check that
this is the estimator record 8 was computed with, before anything is read off the second
band.

### The replication, against `852b1cb` (177 items, 24 occupied blocks)

| | random walk | GARCH |
| --- | --- | --- |
| corrected, recorded | 0.409 | 0.327 |
| corrected, computed today | **0.4092** [0.3532, 0.4747] | **0.3268** [0.2869, 0.4281] |
| forward | 0.3637 [0.3279, 0.4363] | 0.2905 [0.2531, 0.4075] |
| 1 / reverse | 0.7327 [0.6271, 0.7616] | 0.7525 [0.6081, 0.8032] |
| Frisch bounds | [0.3637, 0.7327] | [0.2905, 0.7525] |
| widest | [0.3279, 0.7616] | [0.2531, 0.8032] |
| spread ratio, recorded / today | 0.516 / 0.5162 | 0.468 / 0.4675 |

λ is 0.8889 [0.8562, 0.9678]. Both slopes and both spread ratios reproduce to the three
decimals recorded. "Both Frisch intervals excluding 1.0" holds under either reading: the
bounds and the widest intervals all sit below 1.0 on both baselines. Record 8's predictions
were a corrected slope of 0.25–0.55 against the random walk with the widest interval below
1.0, and 0.15–0.40 against GARCH with its upper bound allowed to reach 1.0. All are met, and
GARCH's did not reach it.

**The intervals in this table are computed today and were never recorded.** They are the
first bounds written down for the replication, not a check of earlier ones. S3 was not
rebuilt; its recorded outcome stands as recorded.

### The open choice, and why no verdict turns on it

The registration does not say whether λ is re-estimated in each resample or held at its
point value. The record settles it: re-estimating reproduces record 8's
[0.3144, 0.4659], and holding λ fixed gives [0.3102, 0.4532]. On the second band a fixed λ
would give [0.3689, 0.4908] and [0.2847, 0.4584]. Neither reading changes a verdict,
because the replication criterion is the widest interval, and λ does not enter it.

### Today's population moves a development bound across 1.0

On the 175 and 174 items the scoring records hold today:

| | development, 175 | second band, 174 |
| --- | --- | --- |
| corrected, random walk | 0.3768 [0.3163, 0.4649] | 0.4098 [0.3564, 0.4754] |
| widest, random walk | [0.2614, **1.0038**] | [0.3307, 0.7577] |
| corrected, GARCH | 0.2522 [0.1635, 0.3431] | 0.3267 [0.2887, 0.4262] |
| widest, GARCH | [0.1358, 1.2428] | [0.2542, 0.7977] |

The replication verdict does not move. The development one does. Record 8 said that against
the random walk compression "survives errors-in-variables, but only just, the upper bound
landing at 0.9993". On 175 items it lands at 1.0038: three SCCO items move it 0.0045, across
the line. Neither sample is the wrong one. The 178 is what record 8 and the registration were
written on, and its σ are exact. The 175 is what the scoring record can produce today.
Development was never the test; it is the post-hoc finding the replication was registered to
check. But "against the random walk it survives" is true of one sample and not the other,
and is not repeated below without the sample it holds on.

### The shape

Same family as [[#61]], out of the same commit, and it reproduced for the same reason: record
8 names its estimator precisely enough to re-implement, down to which baselines λ comes from.
The difference is which result was lost. #61 lost the interval that made a replication
PARTIAL. This one lost every figure behind the finding the write-ups call the only one
established out of sample, and left the verdict standing in prose since 2026-09-05 with
nothing in the repository that could produce it. A verdict that outlives its numbers reads
the same as one that still has them.

### Addendum, 2026-09-29 — S3 rebuilt, because two sentences rest on it

The entry above left S3 standing as recorded. It should not have: S3 is what the README's
"far too narrow for the ones that move" says, and `docs/results.md` cites its recorded
outcome, "all three cut depths were negative and monotone". Record 6 defines it as the
median σ(M.A.P.)/σ(baseline) on the top 6%, 10% and 20% of items by |realised return|
against the rest, each difference with a cluster-robust interval. The cut is on the
realised return, which neither model produced, so selecting on it cannot manufacture a
small σ. It is now `largest_move_cuts` in `mapf.eval.compression`, committed with its tests
before this addendum (`21fcfdb`).

The returns are the persisted `realised_return` where the scoring records hold the item.
For the three SCCO items per band they are the pinned outcome over the forecast's recorded
spot, the route #61 used. The two agree exactly on every item where both exist.

**Development reproduces record 5 exactly, under one reading.** Record 5 reported the
random walk only. All nine of its figures — three medians of the top, three differences,
six bounds, with the rest's medians — reproduce to four decimals when the top set is chosen
once on the whole panel, the generator restarts from the seed for each cut, and the draws
are **2,000**. Re-choosing the top k inside every resample misses by up to 0.05. Record 5
ran at 2,000, the house default of the time; record 6 registered the replication at 4,000,
as records 2 and 4 did. The second band is computed at 4,000.

| second band, 177, 4,000 draws | random walk | GARCH |
| --- | --- | --- |
| top 6% (11) vs rest | 0.5120 vs 0.9107, −0.3987 [−0.4601, −0.2437] | 0.4711 vs 0.8797, −0.4086 [−0.5109, −0.2598] |
| top 10% (18) vs rest | 0.5402 vs 0.9237, −0.3835 [−0.4598, −0.2499] | 0.5196 vs 0.8887, −0.3692 [−0.4487, −0.2318] |
| top 20% (35) vs rest | 0.6461 vs 0.9452, −0.2991 [−0.3964, −0.2279] | 0.6512 vs 0.9010, −0.2498 [−0.3924, −0.2129] |

**The recorded outcome holds against both baselines.** Every difference is negative, all six
intervals exclude zero, and the deeper the cut the more negative the difference. Record 6
predicted a top-cut median of roughly 0.4–0.6, which both meet, and a rest of roughly
0.8–0.9, which GARCH meets and the random walk's 0.91 slightly exceeds. These intervals are
computed today and were never recorded.

**The rounding is the one choice left open.** Record 6 gave fractions, not counts, and 20%
of 177 is 35.4. Nearest gives 35; rounding up gives 36, and −0.2975 [−0.3911, −0.2293] and
−0.2439 [−0.3806, −0.2129]. Both readings give 11, 18 and 36 on development's 178, where the
counts came from. No verdict changes.

**Development against GARCH, never recorded, is not monotone.** Its 6% and 10% cuts are
−0.2742 and −0.2745, the deeper one less negative by 0.0003; the 20% cut is −0.2388. All
three intervals exclude zero. On the second band, the registered test, both baselines are
monotone. On the populations the scoring records hold today (175 and 174) nothing changes:
the second band is negative, excluding zero and monotone on both baselines, and development
against GARCH is still out of order by 0.0006.

---

## 67 · Three tests that passed only on the machine that wrote them

Setting up CI (ADR 0037) meant running the gate on a clean clone first, and three tests
failed there that had never failed here.

- **Two export tests read the real ledger.** `test_no_prices_omits_the_series_and_the_exporter_states_the_absence`
  and `test_prices_are_exported_by_default` called the export helper without
  `--ledger-path`, which therefore defaulted to `var/corpus/ledger.jsonl`, the
  checkout's own 734-line ledger. It is gitignored. Here it exists and the tests passed;
  in a clone the export refused with "the corpus ledger is missing" and both failed.
- **One front-end test read the export unguarded.** "and the two really do differ in
  this export" opened `ui/assets/export/runs/by_source/corpus.json` with a plain `it`.
  Every other export-reading test uses `itNeedsExport`, which skips with a reason when the
  export is absent, so a clone reported 100 passed, 117 skipped and this one crashed.

The fixes are the ones the suites were already designed around. The export helper now
passes a temporary `--ledger-path` unless a test names its own, and the two tests say
`--allow-partial` like their siblings; they pass with the real ledger moved aside. The
front-end test uses `itNeedsExport`.

Same family as [[#62]], which was the same defect one path over: a helper that isolated
six paths of seven and let the seventh default to the repository's real data. #62 fixed
`--runs-dir` and left `--ledger-path`, because the fix was to the path that had been seen
rather than to the helper's rule. The rule is now in the helper: every path is isolated
unless the test supplies one.

**The practical rule:** a test that passes in the repository it was written in has shown
only that. Gitignored data is exactly what a hand-run gate on one machine can never be
missing, so only a clean checkout finds this class. That is the case for CI that #65 did
not make — #65 was about a check nobody ran, and this is about a check that ran every time
on the one machine where it could not fail.

### Addendum — the first CI run found three more

The clean clone was run under `TZ=UTC` before the workflow was committed, and the first
run on GitHub still failed eight tests. None of them fails on this machine.

- **Six read history a shallow checkout does not have.** The forecast- and
  freeze-digest tests rebuild past records from named commits — `ee492d7`, `318250f`,
  `0d78326` — and the default checkout is one commit deep, so every lookup returned
  `None`. The Python job now fetches full history. Every commit a test names was checked
  to be reachable from `origin/main`, since a local clone also holds pre-rebase objects
  that no remote will ever serve.
- **One read an error box through colour codes.** Typer forces a colour terminal at
  import time when `GITHUB_ACTIONS` is set, so `--split` arrived as escape codes around
  its hyphens and the substring test failed. A suite-wide fixture now switches that off,
  beside the one that already strips `MAP_*` from the environment for the same reason.
- **One verdict turned on the last bit of a float.** The tilt test's U-shaped panel was
  `[0.02, 0.98] * 100`, which makes every resample mean exactly 0.5: both intervals had
  zero width, and whether they "excluded" 0.5 depended on summation order. Locally the
  bounds were `0.5` and `0.5000000000000001`, "not established"; on x86 one landed a bit
  below, "suggestive". The panel is now drawn with real spread and clears 0.5 by 0.049.
  The statistic was not changed: no real panel produces a zero-width interval.

Each of the eight passed every hand-run gate on this machine. That is the whole case: the
hand-run gate and CI are two different checks, not one check run twice.

---

## 68 · Thirty-five style declarations that never applied

Rewriting the fan's styles turned up five custom properties that `analyse.css` reads and
nothing defines: `--mono-sm`, `--mono-md`, `--sans-sm`, `--ink-1` and `--rule-1`, plus
`--mono-lg` and `--serif-lg` once each. Thirty-three declarations in all, every one of them
in the sheet since the live-analysis screen was added (`021d0ed`, 2026-09-28). A
`var()` with no definition and no fallback makes its declaration invalid when the value is
computed, and the property falls back to inheriting — silently. So the absence box, the
horizon control, the marking and the old fan never had the fonts, sizes or rules written
for them. The fan's axis labels, sized by `font: var(--mono-sm)` in a 760-unit viewBox,
came out at the page's body size, scaled up, which is why they looked enormous in every
screenshot of it.

A check across all ten stylesheets found two more: `system.css` reads `--sp-8`, the step
after `--sp-7`, for the padding above results and runs cards and the margin above every
page's disclosure. It has read it since `5129f71` (2026-09-26) and nothing has ever defined
it, so those two rules applied nothing either.

The fixes: the seven analysis tokens map to the real ones (`--font-mono` with `--step--1`
or `--step-0`, `--font-sans`, `--ink`, `--rule`), and `--sp-8` is defined as `3rem`, so the
two `system.css` rules now apply as written. That second change moves the results, runs and
disclosure spacing on every screen; it is what was intended, not a redesign.

**A test now fails on any `var()` that has no fallback and no definition** in any
stylesheet. It is the check that would have caught all thirty-five, and it could not have
been a unit test of any one component: each declaration was valid CSS, and the browser
reported nothing.

Same family as [[#65]] and [[#67]]: nothing was wrong that any existing check could see. The
node suite builds the DOM against a stub that never loads a stylesheet, and the styles probe
reads computed values for a fixed list of properties, none of which these were.

---

## 69 · The screenshot server could not have answered

#63's repair says the screenshot server runs on `FakeProvider` with a temporary runs
directory, "then a missed intercept produces a fixture-backed answer written somewhere that
is deleted afterwards." The second half is true and the first is not. `tests/fixtures/llm`
holds a `.gitkeep` and nothing else — no `models.json` and no recorded exchange — so a
`map serve --fixtures tests/fixtures/llm` server refuses every analysis at model resolution:
*"model alias … is not loaded; server reports: (none)"*. A missed intercept would have got
that refusal, which is safer than a fixture answer, not less safe. The repair held; its
description was wrong about why.

It could not have been otherwise, and not only because the directory is empty. `FakeProvider`
finds a fixture by the same `request_key` the cache uses — model, rendered prompt, sampling —
and a live prompt carries the day's filing, date and spot price. A fixture matches only the
exact request it was recorded from, so no fixture set can stand in for a new live run.

It surfaced building the loading state, which exists for the minutes a real run takes and
could not be watched without making one. Instead of a fixture, `map serve --replay RUN_ID`
answers Analyse with a recorded run: its own trace, each stage at the gap it recorded
(faster with `--replay-speed`), then the result the export gives that run. It runs nothing,
writes nothing, and says so in the terminal, in the stream and on the page. That is a
different claim from a fixture — the events are real ones from a real run, replayed — and
it is labelled as that claim.

The `--fixtures` help text and `docs/cli.md` now say a fixture matches only the request it
was recorded from.
