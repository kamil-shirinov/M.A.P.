# 0039 — Live prices on a company page, in the local app only

**Status:** accepted · **Date:** 2026-09-30 · **Builds on** [0036](0036-live-analysis.md) · [0003](0003-price-adjustment-semantics.md) · [0012](0012-price-cache-and-retroactive-adjustment.md)

## Context

A company page showed the pinned price snapshot: a series ending on 2026-09-05, three
weeks before the page was read. That is right for the record — every scored figure was
computed against that snapshot and nothing newer — and wrong for a reader asking what the
company is worth now, or what happened since.

The two things a reader wants, the price now and the closes to today, exist only at the
provider, Yahoo Finance, reached through `yfinance`. Two constraints bound any answer:

- **The hosted copy has no server** (ADR 0036), and Yahoo's data is not this project's to
  republish. Whatever is fetched live cannot go into the export.
- **A quote is not a close.** Findings #64 is a run that anchored on a price taken at 15:52
  and called it a close. Nothing that forecasts or scores may read a live price.

## Options

1. **Fetch from the browser.** Rejected: Yahoo does not allow cross-origin reads, and a
   market-data call outside `mapf.data.providers` breaks the rule that every one goes
   through there.
2. **Put the live series in the export.** Rejected: that republishes Yahoo's data on the
   hosted copy, and freezes "live" into a file that is stale the moment it is written.
3. **Two reads on `map serve`, through the providers, drawn only where a server answers.**

## Decision

**Option 3.**

- **`GET /quote?ticker=`** gives the last one-minute bar from `yfinance` (regular hours),
  its time, and whether the market is open.
  - It comes through a new port, `QuoteSource`, apart from `MarketDataProvider`, so no
    code that takes prices for a forecast can be handed a quote.
  - **Open** means New York's clock is inside 09:30–16:00 on a weekday **and** a trade is
    dated today. The clock alone would call a holiday open, since this project knows no
    holidays. The trade alone would call a market open whose last print was yesterday's.
  - The server also says when to ask again: about a minute while open, the next opening
    bell while shut, and five minutes when it is inside hours with no trade. The page
    never needs New York's hours.
- **`GET /prices?ticker=`** now covers exactly the last two years to New York's today,
  rolling daily: 30 Sep 2024 to 30 Sep 2026 today, and 1 Oct 2024 to 1 Oct 2026 tomorrow.
  - It goes through the same cache every run reads, **split-adjusted like the snapshot**,
    and drops the unfinished session as a run does.
  - It is New York's calendar, not UTC's: at 20:00 there it is still that day.
- **The company page**, where a server answers:
  - The quote goes at the top: the price, New York's clock, open or closed, the time of
    the trade, the source, and that it may be delayed.
  - The chart draws the two-year window on a calendar axis, and whatever is newer than
    the snapshot is drawn dashed and labelled at the rule where it begins.
  - A recorded run's marks sit on the line, and its readout keeps the record's figures.
  - A run anchored before the window is counted in a sentence under the chart, and so is
    a run whose anchor session the series does not hold.
  - If the provider has re-based the history since the snapshot (a split), the factor is
    said.
- **Without a server,** the page is exactly as before: the snapshot, and no quote.

## Consequences

- The record is untouched. Scores, run outcomes and the export still come from the
  snapshot; the live window is a view, drawn beside it and marked as newer.
- A page left open asks Yahoo about once a minute while the market is open, through this
  machine. A quote may lag the exchange, and the page says so rather than implying a feed.
- A split after the snapshot moves the whole live line against the record's figures by
  one factor. The markers stay on the line, and the sentence under the chart says by how
  much.
- A market holiday reads as closed, correctly, because nothing traded. The page asks
  again every five minutes through it.
