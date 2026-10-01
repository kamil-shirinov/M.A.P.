# 0040 — A price window is refetched once, after the close

**Status:** accepted · **Date:** 2026-10-01 · **Builds on** [0012](0012-price-cache-and-retroactive-adjustment.md) · [0039](0039-live-prices-in-the-local-app.md) · **Relates to** Findings #64

## Context

The price cache keeps a window for the whole UTC day: the key is
`{ticker}/{basis}/{fetched_on}/{start}__{end}.parquet`, and `fetched_on` is a date. A run
reaches that key through `execute`, which asks for the window ending on `as_of`'s date,
two years back. Nothing in the file says when in the day it was fetched, so one fetched
before 16:30 in New York is served unchanged after it. Two things go wrong, and the second
is worse:

1. **Fetched before the open, it holds no bar for today.** It is served all evening, and
   today's close appears in the next day's file. This is what was reported.
2. **Fetched during the session, it holds today's bar at that moment's price.** At 17:00
   `settled()` judges the bar by the clock *now*, finds the session over, and passes the
   morning's price as the close. That is Findings #64, a run that anchored on a quote and
   called it a close, reached by a different road: the bar was dropped when it was fetched
   and accepted when it was reread.

The company page's `/prices` read already avoids both, but by a side route: it asks for a
window ending yesterday before 16:30 and today after, so the two are different files.
That is the caller working around the cache, and a run does not.

## Options

1. **Expire a file after N hours.** Rejected: N is a guess, and any N refetches during a
   day when nothing it was waiting for has happened.
2. **Put the settle in the key** (a `{start}__{end}.settled.parquet`, say). Rejected: it
   changes a layout that `PriceSnapshot`, `read_window` (which finds the ticker by path
   depth) and the stored vintages on the laptop all depend on, and it could not be checked
   here against the real `var/prices`.
3. **Record the instant of the fetch in the file, and refetch when a settle has passed.**

## Decision

**Option 3.** Each window is written with `mapf_fetched_at`, a timezone-aware instant, in
its parquet metadata. On a read, a non-frozen cache refetches when

- the file's own instant is before today's 16:30 in New York, **and** 16:30 has now
  passed (`core.sessions.settled_since`), **and**
- the window's end reaches today (an `end` before today holds only finished sessions).

After the refetch the file's instant is past 16:30, so the rule is false for the rest of
the day: **once, not on every read.**

- **The superseded file is moved aside**, to `{name}.parquet.superseded`, not deleted, so
  ADR 0012's rule that an overwritten vintage is an unreproducible run still holds. It
  does not end in `.parquet`, so `PriceSnapshot` cannot offer it as a window.
- **A failed refetch raises and leaves the stale file in place.** Serving it would be the
  defect. The next call tries again. Callers that can show less (the company page) already
  turn the error into "no price history".
- **A frozen vintage never refreshes.** A snapshot that changed on being read would be a
  different snapshot (ADR 0012, pinned vintages).
- **A file with no recorded instant is served as it is.** Every vintage already on disk is
  one. The modification time is not a substitute: a copy or a restore resets it. The
  cost is that a file written today before this change stays as it was until tomorrow.
- 16:30 is `SETTLED_AFTER`, the same instant `settled()` already uses, so the cache and
  the trimmer cannot disagree about when a session is final.
- The rule does not know holidays or weekends, as `sessions.py` does not: on a day the
  market never opened it asks once, and the refetch finds nothing new.

## Consequences

- A run made after 16:30 anchors on a bar fetched after 16:30, or fails. It no longer
  depends on whether someone looked at the ticker that morning.
- One extra request per ticker per day, only for a window that reaches today and was
  fetched earlier that day.
- **Not changed, and worth knowing:** the vintage is still the UTC date. Between 20:00 and
  midnight in New York (19:00 in winter) the UTC date has moved on, so a window read then
  is a new key and is fetched once more, as before. Moving the vintage to New York's date
  would change what `manifest.prices.fetched_on` means for every stored run, which is a
  decision for its own ADR.
- A provider that has not finalised the bar by 16:30 is still read at 16:30 and kept for the
  day. The margin is `SETTLED_AFTER`'s, not this decision's.
