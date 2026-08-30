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

That is the reason for [[Guard Audit]]: one pass over every check in `src/`, asking of each
what its name implies against what it verifies. **Fifteen more gaps, and eleven guards
confirmed sound.** The three recurring shapes are worth more than the list:

1. **Presence standing in for identity** — a file exists where "this run's audit trail" is claimed.
2. **A declared number trusted instead of the thing measured** — this incident's exact shape.
3. **Scope narrower than the sentence** — "this band" without a band filter.
