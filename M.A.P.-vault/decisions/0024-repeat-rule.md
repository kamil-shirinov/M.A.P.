# 0024 — "Transient" is a hypothesis, and the ledger already tests it

**Status:** accepted · **Date:** 2026-08-30 · **Builds on** [0019](0019-corpus-execution-protocol.md), [0021](0021-degeneration-retry.md), [0022](0022-guard-scope.md)

## Context

ALLY 2026-01-21 failed twice with `budget_exhausted`, both times at the analyst's
12,000-token ceiling, in two separate runs of 950 s and 813 s with no cache hits —
so the model genuinely ran to the cap twice. Analyst reasoning across the 32 other
completed items of the band:

| min | median | p90 | max |
| --- | --- | --- | --- |
| 2,085 | 4,412 | 7,459 | **9,094** |

**ALLY is 32% above anything else observed**, and prompt size does not explain it:
ELV has the largest analyst prompt at 3,398 tokens and completed normally.

`budget_exhausted` was classified transient, so it would be retried on **every
resume**, costing a full analyst call and a slot of the failure allowance each time.
That is the `missing_exhibit` shape arriving through a reason nobody classified as
terminal — the exact failure [ADR 0020](0020-context-window-and-truncation.md)
identified for context overflow, in a different costume.

### The stated reason for transience was not true

`ledger.py` justified it as: *"the analyst samples at temperature 0.7, so a second
attempt genuinely explores a different reasoning path."*

**`seed` is fixed for the analyst and goes on every request.** `attempt` reaches the
cache key but never the request body, so a retry sends a byte-identical request.
Whether it explores anything at all depends entirely on the backend declining to
honour the seed — and [[../Findings & Incidents#24]] measured this backend as only
*partially* deterministic. The classification rested on a coin-flip nobody chose, in
the direction where being wrong costs a full analyst call per resume.

That is [[../Guard Audit]] shape 2: a declared property trusted instead of the thing
measured.

## Options

1. **Flip `budget_exhausted` to terminal.** One item lost, no repeated burn.
2. **Leave it transient.** ALLY costs ~15 minutes and an allowance slot every resume,
   forever.
3. **Make terminality evidence-based.** A transient reason resolves an item once it
   has recurred on that item.

## Decision

**Option 3.** A reason classified transient buys an item one retry; a second
identical outcome resolves it. `REPEAT_LIMIT = 2`.

Two samples do not prove determinism — if P(runaway│ALLY) were 0.6, two hits has
p = 0.36 — and that is precisely the argument for not flipping the class. Option 1
answers a question about *one document* by changing the rule for *every* item that
ever exhausts a budget, including ones a retry would have rescued. Option 3 asks the
question of each item separately and lets the ledger answer it.

**The retry is the experiment.** Removing it (option 1) discards the evidence; never
acting on it (option 2) collects the same evidence forever and never reads it.

### The exclusions are the substance

A reason whose cause is *shared infrastructure* says nothing about an item when it
repeats. Five items — WAL, BXP, CP, ELV, LVS — failed together when DNS dropped, and
what they had in common was the afternoon. Excluded:

`inference_unreachable` · `inference_timeout` · `market_data` · `exhibit_unreachable`

Counting is per **(item, reason)**. An item that failed once in the model and once on
the network has one of each, which is two hypotheses rather than a confirmed one.

### Prerequisite: `other` had to be decomposed first

A network failure fetching an exhibit raised `ExhibitError`, which `_reason_for` did
not match, so it landed in `other` — **the same bucket as a genuine model failure**.
The five DNS failures above are all recorded as `other`. Under the repeat rule
without this fix, a second outage spanning two resumes would have burned all five
permanently, and the rule would have caused exactly the damage it exists to prevent.

`httpx` conflates them too: `raise_for_status()` and a dropped socket both raise
`HTTPError`. They are now split at the source, and the order matters —
`HTTPStatusError` is a subclass and must be caught first:

- **`ExhibitUnreachableError`** — DNS, refused connection, dropped socket. EDGAR was
  never reached, so this is a property of the afternoon. Excluded.
- **`ExhibitError`** — a 404, a 500, a malformed document. EDGAR answered, and its
  view of this filing is the same view next pass. **Not** excluded: a repeat here is
  evidence about the item.

`MissingExhibitError` subclasses `ExhibitError`, so it stays ahead of both in the
classifier — a filing with no EX-99.1 must not read as something a retry could fix.

### The comment is now true, and sampling is untouched

The `ledger.py` comment now says what actually happens: the retry is byte-identical
and its usefulness depends on backend non-determinism that #24 measured as partial.
**Sampling is deliberately not changed to fix this.** Varying the seed per attempt
would invalidate every cache key and require a freeze amendment, to improve a retry
the repeat rule makes the last one anyway.

## Consequences

- **ALLY 2026-01-21 is resolved now**, at two failures. One item of 356 (0.28%),
  recorded, and it stops costing 15 minutes and an allowance slot per resume.
- Items resolved this way are reported through `Ledger.exhausted()` and **named
  individually** on resume, not folded into the terminal count. *"This filing has no
  exhibit"* is a fact about the corpus; *"we stopped asking"* is a decision, and a
  decision that removes an item from the sample should not be a number.
- `status_of` now counts any resolved non-complete entry as terminal rather than
  re-testing `is_terminal`, which would have left a finished pass reading as
  permanently outstanding and made `map evaluate` refuse forever.
- The five historical `other` entries were all subsequently completed, so no
  unresolved item carries a legacy misclassification into the new rule.
- `exhibit_error` and `exhibit_unreachable` join `FailureReason`. Neither is terminal
  by nature; only `exhibit_unreachable` is excluded from the repeat rule.

## Pre-registered diagnostic, to run after the band

`scripts/ally_reasoning_replay.py` replays ALLY's recorded analyst prompt five times
and reports the reasoning distribution. **After the clean band completes, not during**
— it loads the 12B and would contend for the model, force KV swaps, and can push a
real item past the 1,300 s read timeout.

The result is recorded either way, because it is a finding about the *method*:

- **Five at the cap** — the runaway is a property of the document, and a blanket flip
  would have reached the same answer here.
- **Some finishing inside the budget** — the runaway is probabilistic, and the repeat
  rule was the better answer, because a blanket flip would also have discarded items
  a retry would have rescued.
