# 0003 — Price adjustment semantics across heterogeneous providers

Status: Accepted · Date: 2026-08-09 · Amended 2026-08-11 · Phase 1

## Context

Phase 1 uses `yfinance` as the primary market-data provider and Stooq (via
`pandas-datareader`) as the fallback. `yfinance` is an unofficial scraper of
Yahoo Finance, throttles at roughly 950 requests per session, and breaks
periodically — which is why the fallback exists.

The two providers do not return the same series. Stooq serves unadjusted OHLC.
`yfinance` back-adjusts for splits and dividends, and its `auto_adjust` default
has changed across releases. A failover part-way through a project therefore
changes what "close" means, silently. Nothing catches it: both frames are
well-formed, both have the right columns, both have plausible values. Every
Phase 2 score computed across that boundary is contaminated in a way that has no
symptom.

## Options

1. **Take whatever the provider returns.** Fastest, and quietly poisons the
   evaluation harness this whole project is judged on.
2. **Store the raw frame and adjust downstream.** Pushes provider-specific
   knowledge past the `data/providers/` boundary, breaching `CLAUDE.md` §4.
3. **Normalise inside each adapter into one canonical semantic.**

## Decision

**`core` defines one canonical price semantic — split- and dividend-adjusted
close — and every adapter is responsible for normalising into it.** An adapter
that cannot produce the canonical form for a given request fails loudly rather
than returning an approximation.

**The adjustment basis and the serving provider are recorded in both the parquet
cache key and the run manifest.** Cache entries written under different semantics
cannot collide, and any run can be traced to the exact series it consumed.

**A window is served by exactly one provider, or it is refetched.** Rows from two
providers are never merged into one series. A partial response is a miss.

**The cross-provider agreement test asserts on daily returns, not price levels.**
Levels differ by construction the moment a dividend or split falls inside the
window, and tolerance-tuning against that is wasted effort. The test fixes a
historical window known to contain no corporate actions for the chosen ticker and
compares daily returns within a tight tolerance. It is marked
`@pytest.mark.network` and deselected by default (ADR 0004 / DoD criterion 6).

### Amendment, 2026-08-11 — the basis is split-adjusted, and the chain is broader

Two corrections, both found while implementing the adapters.

**The canonical basis is `split_adjusted`, not `split_dividend_adjusted`.** Stooq
publishes split-adjusted closes with no dividend adjustment, so under the original
basis the fallback adapter would have raised `PriceAdjustmentUnsupportedError` on
every call — a fallback that existed on paper and would have failed the first time
it was needed. Split-adjusted is also the correct target for a *price* forecast,
and it drifts far less often. Reasoning in full in ADR 0012.

**The chain falls back on any `MarketDataError`**, not only
`MarketDataUnavailableError` as stated below. An empty result from a scraper is
indistinguishable from a scraper failure, and with two providers one extra request
costs nothing against a spurious hard failure. The original wording is left in
place above so the change is visible rather than rewritten away.

## Consequences

- Each new provider costs a normalisation implementation and an entry in the
  contract-test suite. This is the intended tax on adding a provider.
- The corporate-action-free window is a fixture that must be chosen once and
  pinned. If the reference ticker later has a split inside it, the test breaks
  and the fixture is re-pinned — the failure is legible.
- The cache is partitioned by adjustment basis, so changing the canonical
  semantic invalidates the price cache. Acceptable; it should change rarely.
- Provider failover is recorded, never inferred. A run whose manifest names Stooq
  is a run whose results should be read knowing yfinance was unavailable.
