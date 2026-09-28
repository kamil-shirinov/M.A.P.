# 0036 — Live analysis: a forecast made on demand, and what may be said about it

**Status:** accepted · **Date:** 2026-09-28 · **Builds on** [0031](0031-holdout-spend.md), [0032](0032-calibration-form.md), [0033](0033-phase-3-outcome.md), [0034](0034-document-provenance.md), [0035](0035-run-journal.md)

## Context

Until now every screen has been a read. `map export` writes flat JSON, four pages read it,
and nothing in the browser can cause a forecast to exist. That boundary is why the hosted
copy is safe to publish and why the journal cannot compute a score.

Live analysis breaks it deliberately: type a ticker, press Analyse, and watch a forecast
being produced from the company's latest Item 2.02. The pipeline for this already exists
— `map run --from-edgar` discovers the filer's most recent earnings 8-K, runs the three
agents, and writes a run directory whose manifest carries `document_source: "edgar"`. What
does not exist is a way to ask for one from a page, and a way to show the answer without
implying more about it than the evidence supports.

Four things make this harder than adding an endpoint.

**The calibration was fitted on a panel, and a live ticker is not in it.** ADR 0032's map
`z → (z − a) / b` was fitted on 175 development items at a five-session horizon, drawn from
120 companies selected by the filters in `corpus/selection.py` over two fixed calendar
windows, anchored one trading day after each filing. It generalised out of sample to the
holdout — but the holdout is the *same panel's* other half. Applying it to an arbitrary
live ticker at an arbitrary horizon is extrapolation, and a fan drawn with it looks exactly
like a fan drawn without it.

**The raw fan is the one measured too narrow.** Calibration ratio 0.733 on development,
0.592 on the holdout, both intervals excluding 1.0. So showing the raw fan as the unmarked
default would be showing the known-bad thing by default, and showing the corrected fan
everywhere would be claiming a correction that was never tested where it is being applied.
Neither can simply be the default.

**A local server is a local server until it is not.** Binding to `127.0.0.1` is not a
security boundary. DNS rebinding turns any page the visitor has open into a client of it,
and a plain cross-origin `POST` needs no rebinding at all. Each analysis costs minutes of
local inference and writes a permanent journal entry.

**Every live run is permanent.** It lands in `runs/`, it is counted by `map runs`, and it
is exported. There is no discard. A demo that produces runs casually pollutes a journal
whose composition is already the subject of ADR 0035.

## Options

**A — no server; a CLI command and a page that reads the result afterwards.** Safest, and
it is what exists. Rejected because the thing being asked for is watching a forecast being
made; a two-step "run this, then reload" is a different product.

**B — a server that reuses the export's file layout, writing each live run into the export
and letting the existing pages read it.** Rejected: it makes a live run indistinguishable
from a corpus run at the data layer, which is exactly the confusion `corpus_relation`
exists to prevent, and it means the hosted copy could accidentally carry one.

**C — a small local server with its own endpoint and its own result view, where the
marking is part of the view from the first commit.** Chosen. The result view is built with
the calibration marking in it rather than gaining it later, so no version of it ever
renders an unmarked fan.

**On the calibration rule specifically**, the rejected alternative was a numeric
"closeness" score — how similar this company is to the panel — used to fade the marking.
Rejected because it invents a continuous quantity nothing measured, and a half-marked fan
is read as a mostly-fine one.

## Decision

### 1. The corrected fan is the exception, not the default

The fitted correction is applied **only** when all three hold:

- **the horizon is exactly five sessions** — the only horizon anything was fitted at;
- **the anchor is within one trading day of the filing** — the panel's point-in-time
  alignment, which puts the overnight announcement gap outside the window;
- **the company would pass the corpus's company-level filters.**

Otherwise the **raw** fan is drawn, marked amber, with **the failing condition named on
screen**. Amber keeps the one meaning it was narrowed to: a number that is not a settled
measurement.

"Company-level filters" is four of the seven `RejectionReason` values, and the distinction
is load-bearing. `no_cik`, `no_price_history`, `illiquid` and `no_exhibit` are properties
of the company and are checkable on a live ticker. `duplicate_cik`, `too_few_filings` and
`not_reached` are properties of **how the panel was drawn** — a seeded ordering across two
fixed calendar windows — and cannot be evaluated for a single filing today. They are not
approximated and not silently passed: they are simply not part of the test, and this ADR is
where that is written down.

### 2. `corpus_relation` is decided by the existing check, not asserted

A live run's relation to the frozen corpus is whatever `mapf.eval.journal` already computes
from the document identity: `ledger_item`, `repeat_of_exhibit`, `outside_corpus` or
`unchecked`. Nothing in the live path hardcodes `outside_corpus`.

A corpus company's latest Item 2.02 may well already be a frozen exhibit, in which case the
honest answer is `repeat_of_exhibit` — same document, new run — and the journal already has
that word. Asserting `outside_corpus` because the request came from a browser would be the
page telling the data layer what it found.

### 3. Host and Origin are checked, and the app and the endpoint share one server

`POST /analyse` refuses unless the `Host` header names a loopback address the server is
actually bound to, and unless `Origin`, when present, matches the server's own origin. The
app and `/analyse` are served by **one** server so that same-origin is the normal case and
a cross-origin request is always wrong.

Binding to loopback is kept as well, but it is not the check. It stops a machine on the
network reaching the port; it does nothing about a page in the visitor's own browser.

### 4. The hosted copy states one absence per page, not a disabled control per row

The published site is a static record with no server behind it. It carries **one stated
absence on each page that would otherwise offer analysis**, in the existing absence
vocabulary — naming what is missing and why — rather than rendering rows of controls that
cannot work.

A disabled button per row asserts, dozens of times per screen, that the feature is
*temporarily* unavailable. It is not: nothing is queued, pending or retrying, because there
is no server to accept the request. That is the same claim the search screen's refusals
section already makes, and it is made once.

### 5. `map export --check` must show only EDGAR runs moving after a live run

A live run changes exactly one thing about what an export would say: the count of runs whose
`document_source` is `edgar`. The freeze, the code, the ledger, the symbol vintage and the
price snapshot are all untouched.

So the run counts join the identities `--check` compares, and **a test asserts that a live
run moves the EDGAR count and nothing else**. If a live run ever moves `ledger.items_settled`
or a freeze digest, something has written into the corpus, and this is the check that says
so before an export carries it.

## Consequences

**A corrected fan still is not a calibrated one.** Even with all three conditions met, the
company is outside the frozen corpus and the correction's out-of-sample evidence is about
the panel, not about arbitrary tickers. The three conditions make the application defensible,
not verified. The result view says which conditions were met rather than printing a word
like "calibrated".

**Most live runs will be amber**, because the third condition is a real screen — the
liquidity floor alone is $50M median dollar volume. That is the intended outcome. A marking
that almost never fires would not be doing anything.

**Runs are counted and reported, not discarded.** Every live run is a permanent journal
entry. Development against `FakeProvider` costs nothing and produces nothing; real runs are
made only from a clean, committed tree, and how many were made is stated.

**The local path and the hosted path diverge**, and that is now a property of the build
rather than an accident. One serves an app plus an endpoint; the other is files. The test
suite covers both, and the export contract is what keeps them honest.

**Unresolved, and deliberately so:** the period selector. Ten and twenty-one sessions are
offered and are always amber under rule 1, since nothing was fitted at either. Whether the
fitted correction *should* apply to live five-session runs at all is the question rule 1
answers conservatively; if a later phase measures live runs against outcomes, that evidence
replaces the rule rather than adjusting it.
