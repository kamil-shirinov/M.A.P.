# 0021 — The degeneration retry, and what it must not cost the other 354 items

**Status:** accepted · **Date:** 2026-08-29 · **Builds on** [0018](0018-corpus-band-and-panel-shape.md), [0019](0019-corpus-execution-protocol.md), [0020](0020-context-window-and-truncation.md)

## Context

Two corpus items — one STZ filing and one FCX filing — stopped intake at its
2,048-token cap. [ADR 0020](0020-context-window-and-truncation.md) had already
classified a truncated output as **terminal**, so the default behaviour was to fail
them: 2 of 356 is 0.56%, well inside the 8-item allowance.

Before accepting that, the tails were read. **They are not long documents. They are
decoding loops.**

| | STZ | FCX |
| --- | --- | --- |
| output | 18,938 tokens | at the cap |
| lines | 757 | 53 |
| **unique lines** | **22** | **21** |
| redundancy | **97.1%** | 60% |
| last new content | line **27** | line 29 |
| most-repeated line | **187×** | — |

STZ produced twenty-eight real facts and then repeated a four-line block roughly
180 times until the cap stopped it. FCX is the same failure with a longer period: a
~22-line block repeating verbatim.

**Size does not predict it.** ALLY is a *larger* document than STZ (51,188
characters) and produces 543 clean tokens. Across six measured items intake's
natural output is 252–543 tokens on inputs from 1,973 to 51,188 characters — flat.
So the cap was never the constraint, and raising it would not have helped: **a cap
sized to "what it wants" is meaningless when what it wants is unbounded.**

## Options

1. **Keep it terminal.** Fail both items. Nothing changes.
2. **Apply a frequency penalty corpus-wide.** Fix the cause for every item.
3. **Apply a frequency penalty only as a retry**, after a first attempt has been
   cut off.

## Decision

**Option 3.** `frequency_penalty = 0.3`, applied to **intake only**, and only on a
retry after a truncated first attempt. One retry. If the retry also loops, the item
fails `output_truncated` as before.

### Why not simply fail them: the loss would be asymmetric between bands

This is the argument that decides it, and it is not about the number 2.

The panel is built on a **same-ticker constraint across bands**
([ADR 0018](0018-corpus-band-and-panel-shape.md)): every ticker appears in both the
clean and the ambiguous band, so the leakage difference the study exists to measure
is a within-ticker comparison. STZ and FCX each carry 3 clean items and 3 ambiguous
items.

Intake runs at temperature 0, so **degeneration is a property of the document, not
of the ticker.** One filing loops; its five siblings need not. Failing the two
observed items therefore removes 1 of 3 clean items for STZ and 1 of 3 for FCX
while their ambiguous counterparts survive — an **unbalanced panel on exactly the
axis the design protects.** That is a different and worse defect than a smaller
sample: it is a sample whose imbalance correlates with the comparison being made.

FCX compounds it. FCX is already in the truncation set
([ADR 0020](0020-context-window-and-truncation.md)), whose pre-registered
sensitivity check reports the result with and without BXP, FCX and PRU. Dropping an
FCX item asymmetrically weakens the very check that exists to show truncation did
not drive the result.

**The raw count is the weaker argument and is recorded second: 2 of 356 is 0.56%.**

### Why not corpus-wide

The fix works. Replaying the exact recorded prompts:

| item | penalty 0.0 | 0.3 | 0.6 |
| --- | --- | --- | --- |
| **STZ** | 2,048, **cut off** | **350, completed** | 640, completed |
| **FCX** | 2,048, **cut off** | **1,171, completed** | 492, completed |
| normal A | 222 (9 lines) | 420 (18 lines) | 394 (17) |
| normal B | 517 (27 lines) | 409 (21 lines) | 433 (19) |
| normal C | 159 (7 lines) | 197 (9 lines) | 172 (8) |

Both loops break cleanly and both items complete. **But it changes every
well-behaved item measured** — one nearly doubled in length, one shrank by a fifth,
and none was unchanged. Applying it by default means perturbing the inputs the
analyst reasons from for 354 items in order to rescue 2, with no measurement of what
that does to forecast quality. That is the trade this project exists to refuse.

**0.3 rather than 0.6** because 0.3 is the smallest tested value that breaks both
loops, and a penalty is a distortion: the least of it that does the job is the right
amount. 0.6 also works and is not better.

### Why intake only

The analyst already samples at **temperature 0.7**, which breaks loops on its own —
and its truncation has a different cause (a reasoning budget), already handled as
`budget_exhausted`. The structuralist decodes against a **JSON Schema**, which makes
an unbounded repeat unreachable by construction ([ADR 0002](0002-constrained-decode-surface.md)).
Neither is configured with a penalty, and the retry is disabled entirely when none
is configured rather than applying a zero penalty — which would still change the
request body.

### What "one retry" means, precisely

The retry **replaces** its first attempt: the same prompt is re-run, and the looped
output is discarded before anything downstream sees it. This is the opposite of the
structuralist's repair loop, which is built **from** the bad response and feeds it
into the next prompt.

That distinction is load-bearing in the trace. `truncated_output` is **sticky** —
any cut-off attempt flags the stage, and a later repair does not clear it, because
the repair inherited the fragment. A degeneration retry is the one thing that
clears it, and only because it throws the fragment away. Getting this backwards in
either direction is a real defect: blanket stickiness fails an item that was
repaired, and blanket last-wins passes an item built on a truncated repair.

The retry also takes a **distinct cache slot** (`attempt + 1`). Same prompt, same
model: without it, the retry could be served the looped response straight from the
cache ([ADR 0001](0001-cache-key-composition.md)).

## Pre-registered sensitivity check

**The primary result will be reported both with and without every item that took a
degeneration retry, regardless of what the comparison shows.**

Declared here, on 2026-08-29, **before any item of the clean band has run and before
any score exists anywhere.** These items were produced under different sampling
parameters from the rest of the corpus, and a robustness check run afterwards and
mentioned only when it is favourable is a different claim from one committed to in
advance. If the two differ materially, that difference is a finding and is reported
as one.

This is the same commitment as the truncation check in
[ADR 0020](0020-context-window-and-truncation.md), and the two partitions overlap:
FCX is in both. They are reported separately, not merged.

The check needs the partition to be recoverable, so the flag is written in three
places: `AgentRecord.degeneration_retry` in every manifest, `LedgerEntry.
degeneration_retry` with the agent names in the ledger, and a per-item `NOTE` on
stdout while the run happens. A partition that requires opening 356 manifests to
reconstruct is one that quietly does not get run.

## Consequences

- **`SamplingParams` gains `frequency_penalty`**, which is in the cache key. Adding
  the field changes the key payload for *every* entry, so **the whole LLM cache is
  invalidated.** This is deliberately being done now, before the run starts, when
  the cache is empty by choice. The same change made on night four would cost every
  night before it.
- **The manifest records the sampling that ran, not the sampling that was
  configured.** A retried agent's `AgentRecord.sampling` carries the penalty,
  because those are the parameters that produced the response. `manifest_version`
  goes to **1.4.0**.
- **The trace records sampling per call.** It did not before, which meant the audit
  trail could not show which attempt carried a penalty — an unauditable retry in
  the artifact whose whole purpose is auditing.
- **Truncation is now checked after *each* agent** rather than once after all three,
  so an item that cannot succeed fails before paying for two more model swaps.
- An ordinary call is byte-identical on the wire to one made before this existed: an
  unset penalty is omitted from the request body, not sent as null. A test asserts
  it, because the corpus-wide claim depends on it.
- The failure allowance is unchanged. If a retry loops again the item still fails
  `output_truncated`, still terminal.
