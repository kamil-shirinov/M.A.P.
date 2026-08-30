# 0023 — The three adapters between stored artifacts and a score

**Status:** accepted · **Date:** 2026-08-30 · **Builds on** [0012](0012-price-cache-and-retroactive-adjustment.md), [0018](0018-corpus-band-and-panel-shape.md), [0019](0019-corpus-execution-protocol.md), [0022](0022-guard-scope.md)

## Context

The scoring pass, the baselines, the Monte Carlo mixture and the aggregation all
existed before `map evaluate` could produce a number. What was missing was the
join: getting stored forecasts and realised prices into them.

Adapters are where a correct engine produces a wrong answer. Each of the three
below has a plausible-looking implementation that is silently wrong, and none of
the three failures announces itself.

## Decision

### 1 · The scored set comes from the ledger, never from scanning `runs/`

`runs/` is not a corpus. It holds `first-capture`, `first-capture-v2` and a drift
of loose UUIDs from the first live forecasts, produced under different prompts, a
different horizon and an older schema. A pass that walked the directory would find
them, and several would parse far enough to be scored.

This is the reasoning that killed resume-by-scanning in
[ADR 0019](0019-corpus-execution-protocol.md), applied to the other end of the
pipeline: an entry in the ledger is a promise that a specific item completed and
left artifacts behind, while a directory on disk is evidence only that something
once ran.

**Three refusals, all loud:**

- **An item the frozen corpus does not contain.** The ledger and the corpus have
  diverged, so every rate reported afterwards would have the wrong denominator.
- **A completed item recording no run id.** Skipping it would remove from the
  sample exactly the items whose bookkeeping is broken — a selection effect, not a
  smaller sample.
- **A forecast that does not match its ledger entry.** Wrong ticker, or dated
  outside the window that follows its filing. A file in the right directory is not
  proof it belongs to the right item ([ADR 0022](0022-guard-scope.md)), and scoring
  it would attribute one ticker's forecast to another's outcome.

Unreferenced run directories are **reported and never refused.** Their existence is
not an error, and naming them is how the decision to load from the ledger stays
visible instead of being invisible good behaviour.

### 2 · One vintage, across both endpoints and across the band

A realised return is a ratio of two prices, and a ratio means something only when
both sides share a measurement basis.

**Within one item this already held, and the assertion is worth stating anyway.**
Both endpoints are bars of a single `PriceWindow`, which carries one provider and
one adjustment for the whole series. The specific failure of a split landing
between forecast and scoring is also already caught: re-adjustment moves *both*
endpoints, and `SpotDriftError` fires on the first one, because the recorded spot
no longer matches. So the window's basis is now asserted against the canonical one
rather than assumed — "by construction" being a claim about code that changes — but
this is defence in depth, not a repair.

**Across the band it did not hold, and that is the reachable failure.**
`ProviderChain` fails over **per call**, so one ticker can be served by yfinance and
the next by stooq. The price cache is keyed by `fetched_on`, so a scoring pass
spanning midnight mixes two vintages. Both produce well-formed windows that silently
mean different things, and every number downstream — the paired difference, the
leakage estimate — assumes one series. ADR 0012 states the obligation as *"Phase 2
must refuse to score across mixed values"*; `_require_one_vintage` is where it is
refused.

### 3 · Earnings dates are a point-in-time question

The earnings-multiplier baseline is the likeliest place for look-ahead to re-enter,
because **"the ticker's earnings dates" reads as a static property of the company**
rather than as something with an as-of date.

It was already safe, and safe by accident. `earnings_multiplier` locates each date
in an already-truncated history, so a future date simply fails the lookup and is
dropped. **Silently.** An adapter handing over the full calendar would look correct
forever, and the day the history stopped being pre-truncated the look-ahead would
arrive with nothing to announce it.

Two changes, and the first is the one that matters:

- **The contract carries the date.** `earnings: Callable[[str, date], Sequence[date]]`.
  Asked for "the ticker's earnings dates" an adapter returns all of them; asked *as
  of* a date, it has to answer a point-in-time question. A look-ahead becomes
  something a caller writes on purpose rather than something it inherits.
- **`score_item` raises on any date at or after `as_of`.** Filtering would restore
  the silence.

The calendar itself comes from the frozen corpus — EDGAR-dated Item 2.02 filings,
already frozen and verified, needing no second source and no network, and unable to
shift between one scoring pass and the next. **The limitation, stated:** it holds
only the *selected* filings, so a ticker offers at most a handful of prior windows.
`earnings_multiplier` returns a neutral 1.0 below its evidence threshold, so a thin
history weakens the baseline rather than corrupting it. That makes the earnings
baseline weaker than one fitted on a full history would be, which is a property of
the comparison and must be reported as one.

## The pre-registered checks run unconditionally

[ADR 0020](0020-context-window-and-truncation.md) and
[ADR 0021](0021-degeneration-retry.md) both committed, before any score existed, to
reporting the primary result with and without an identified subset *regardless of
what the comparison shows*. `map evaluate` runs both every time rather than behind a
flag, which is what keeps a pre-registration from decaying into an option.

**Writing the test for that found the partition was broken.** It keyed the excluded
set on the ledger's `filing_date` and the scored items on the forecast's `as_of` —
which is the day *after* the filing, so the sets could never intersect. Both checks
would have reported "no items in the set" for the entire corpus, forever, and an
empty subset reads as *nothing was affected* rather than as a broken partition. The
pairing is now carried through the loader (`Loaded`) instead of being reconstructed
from dates.

## Consequences

- `mapf.corpus.forecasts` is a new module. It sits in `corpus` rather than `eval`
  because `eval` is below `corpus` in the layer order and may not reach up to the
  ledger; `score_band` still takes plain callables and imports no adapter.
- `ScoredItem` carries `provider` and `adjustment`, which is what makes the
  band-level vintage refusal possible at all and lets the report name the series it
  scored against instead of leaving the reader to assume one.
- `map evaluate` reports leakage when the *other* band is finished and names it as
  absent when it is not — never partially, for the reason the pass boundary exists.
- The unit tests score end to end against a generated series with `build_market_data`
  patched out. No unit test reaches the network.
