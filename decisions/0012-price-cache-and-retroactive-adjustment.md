# 0012 — The price cache and retroactive adjustment

Status: Accepted · Date: 2026-08-11 · Amended 2026-08-12 (twice) · Phase 1

## Context

Adjusted prices change retroactively. A dividend or split alters the adjustment
factor applied to **every prior close**, so a parquet file written today will not
match a fresh fetch next month: same ticker, same range, same key, different
numbers. Nothing fails. It is ADR 0003's failure mode arriving through a second
door — and it is worse than the first, because the first needed two providers to
disagree while this one needs only the passage of time.

The consequence lands in Phase 2. Scoring compares a forecast made at *T* against
the realised move from *T* to *T+h*. If half a backtest reads one adjustment
vintage and half another, the scores are meaningless and no test catches it.

Two facts are worth stating precisely, because they bound the problem and neither
is obvious.

**Back-adjustment makes the whole history a function of the fetch date.** The
value is not `close(t)`; it is `close(t | fetched_on)`. A cache keyed on
`(ticker, start, end)` is keyed on the wrong thing — it is missing a dimension the
data varies along.

**Returns inside a window are invariant to actions that fall outside it.**
Back-adjustment multiplies every price before an action by the same factor, so an
action occurring *after* `window_end` rescales the whole window uniformly and
cancels in every return computed within it. Contamination therefore requires an
action that falls **inside** the window **and** between two fetches. That is a
narrow target, and it is why the frequency of actions matters so much.

## Options

1. **Ignore it.** Silent contamination, discovered — if ever — in Phase 2.
2. **Cache raw OHLC plus a corporate-actions table, adjust at read time.**
3. **Cache the adjusted series, with fetch date and basis in the key and the
   manifest**, so vintages are distinguishable rather than mixed.

## Decision

**Option 3, plus a change to the canonical basis that does most of the work.**

### The canonical basis becomes `split_adjusted` (amends ADR 0003)

ADR 0003 chose split-**and-dividend**-adjusted close. That was wrong, for three
reasons, and the first is disqualifying:

1. **Stooq cannot produce it.** Stooq publishes split-adjusted closes with no
   dividend adjustment. Under the old basis the fallback adapter would have had to
   raise `PriceAdjustmentUnsupportedError` on every single call — the fallback
   existed on paper and would have failed the first time it was needed, which is
   precisely when nobody is in a position to debug it.
2. **It is the wrong target.** `price_modifier_pct` forecasts a *price* move. A
   dividend-adjusted series measures total return, so scoring a price forecast
   against it would credit or penalise the model for dividends it was never asked
   about.
3. **It shrinks the drift surface by an order of magnitude.** Splits are rare —
   a handful per decade per ticker. Dividends are quarterly. Choosing the basis
   that only moves on splits means the retroactive-drift window is measured in
   years rather than months.

Both adapters can produce it: Yahoo's `Close` with `auto_adjust=False`, and
Stooq's `Close` as published. Neither needs an actions table.

### The cache key carries the vintage

`var/prices/{ticker}/{basis}/{fetched_on}/{start}__{end}.parquet`, with the
serving provider in the file's own metadata. The manifest records basis, fetch
date and provider. Two runs on different vintages are distinguishable by
construction and can never be silently mixed.

`fetched_on` in the key is a **conservative proxy**: it forces a refetch on a new
day even when no corporate action occurred, which is almost always. The cost is
one request per ticker per day. The alternative — keying on the actions that
actually matter — requires the actions table this decision defers.

## Why not option 2 in Phase 1

I agree it is the correct end state, with one correction: **raw + actions does not
remove the problem, it relocates it.** The actions table grows too, and
back-adjusting from raw plus a *newer* actions table rescales history exactly as
before. What option 2 actually buys is that the **raw** series is immutable and
the adjustment becomes reproducible *given a recorded actions snapshot* — so the
snapshot must be versioned as carefully as the prices, or nothing is gained.

Deferred for Phase 1 because it costs a second scraper surface (Yahoo's actions
endpoint), a snapshot-versioning scheme, and an adjustment implementation whose
correctness would itself need a test corpus — all to improve on a basis that,
having moved to split-only, now drifts on the order of once every few years per
ticker.

## What Phase 2 needs, and whether this blocks it

**It does not block Phase 2, on one condition that must be written into the
evaluation harness:** a scoring corpus must be fetched in a **single pass**, and
the pass's fetch date recorded. Every window then shares one vintage and the
comparison is internally consistent, which is all a score requires.

Phase 2 must additionally:

- **Read `adjustment`, `provider` and `fetched_on` from the manifest and refuse to
  score across mixed values**, or report them as separate populations. This is the
  concrete obligation this decision creates.
- Treat a corpus assembled incrementally over weeks as suspect until proven
  single-vintage.

### Amendment, 2026-08-12 — `schema_version` is the same class of obligation

`forecast.json` moved from `1.0.0` to **`2.0.0`** when `price_modifier_pct` became
`price_return` and its units changed from percentage points to a decimal fraction.

It belongs here rather than in a separate ADR because it is structurally identical
to the adjustment-basis problem: **a reader that ignores the marker parses the
artifact without error and is wrong by a constant factor.** A 1.x consumer reading
a 2.0 forecast sees `0.045` where it expects `4.5` and silently produces scores a
hundred times too small. No exception is raised, nothing looks broken, and the
result is a plausible number.

So the Phase 2 obligation is the same, and now has three parts rather than two.
**The evaluation harness must read `schema_version`, `adjustment`, `provider` and
`fetched_on`, and refuse to score across mixed values** — or report each population
separately. Any of the four differing is a reason to separate, not to reconcile.

The version is a `Literal` on `Forecast`, so an artifact carrying the wrong one
cannot be constructed, and an old artifact fails validation loudly rather than
being coerced.

**Correction, later the same day.** The obligation above was unmeetable as written.
Phase 2 reads the *manifest* to decide whether to score, and the manifest carried
only its own `schema_version` — which read `1.0.0` while the forecast beside it
read `2.0.0`. A harness following this ADR to the letter would have read the wrong
number, found it consistent across every run, and scored the whole corpus.

Caught by the first successful v2 run, from printing the manifest rather than
trusting it. The manifest now carries `manifest_version` for its own format and
`forecast_schema_version` for the artifact it describes, and a test asserts they
differ so the two can never be confused again.

The general lesson is sharper than the fix: **an obligation on a downstream
consumer is only as good as the field it names actually meaning what the ADR
assumes.** Two fields called `schema_version` in adjacent files, describing
different things, is precisely the silent-and-plausible failure this ADR was
written about — reproduced inside the mitigation for it.

If Phase 2 later needs total-return scoring, or a corpus that spans a split, that
is the point at which option 2 becomes necessary. This decision is designed to be
replaceable rather than permanent: the basis is a `Literal` on `PriceWindow`, so
adding one is a typed change that fails loudly everywhere it matters.

## Consequences

- A new day means a cache miss and one refetch per ticker. Acceptable at Phase 1
  volume; yfinance throttles at roughly 950 requests per session.
- Old vintages accumulate on disk rather than being overwritten. That is
  deliberate — an overwritten vintage is an unreproducible run — and `var/` is
  gitignored and disposable.
- A window is served by exactly one provider or refetched. Rows from two providers
  are never merged, so a single series always has one basis and one source.
- The chain falls back on any `MarketDataError`, not only
  `MarketDataUnavailableError` as ADR 0003 first stated. An empty result from a
  scraper is indistinguishable from a scraper failure, and with two providers the
  cost of one extra request is negligible against the cost of a spurious hard
  failure.
