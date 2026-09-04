# Findings & Incidents

Real bugs and discoveries, in the order they appeared.

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
