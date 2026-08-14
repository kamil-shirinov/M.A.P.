# 0013 — We forecast price, score price, and flag the windows where those diverge

Status: Accepted · Date: 2026-08-11 · Phase 1

## Context

ADR 0012 moved the canonical basis to `split_adjusted`. That fixed the fallback
and shrank the retroactive-drift surface, and it introduced a second problem that
lands squarely in Phase 2.

**A split-adjusted series retains the ex-dividend drop.** On the ex-date the price
falls by roughly the dividend — one to two percent in a single day for a
high-yield name. In the series that is an ordinary decline, indistinguishable from
a real one.

Phase 2 scores a forecast of a price move against the realised price move. If an
ex-date falls inside the forecast window, the model is penalised for a mechanical
drop it had no information about and could not have forecast. Worse, the penalty
is systematic rather than random: it applies to every high-yield name, in every
window containing an ex-date, always in the same direction. That is not noise, it
is bias, and a calibration study run on top of it would be measuring the dividend
calendar.

## Options

1. **Switch to dividend-adjusted prices.** Removes the drop and re-introduces
   everything ADR 0012 rejected: Stooq cannot produce it, and the drift surface
   goes back to quarterly.
2. **Ignore it.** Phase 2 silently measures the dividend calendar.
3. **Forecast price, score price, and record where the two diverge mechanically.**

## Decision

**Option 3.** The forecast target does not change: `price_modifier_pct` is a price
move, and it is scored against a price move. What changes is that the run records
enough for Phase 2 to know when that comparison is contaminated.

The manifest carries a `dividends` block for the forecast window
`[as_of_trading_date, +horizon_days]`:

- `ex_dates` — ex-dividend dates known to fall inside the window
- `total_amount` — their sum, in the quote currency
- `known` — **whether the question could be answered at all**
- `source` — where the answer came from

`known` is the field that matters and it is not decoration. The forecast window is
in the future at run time, so an ex-date inside it may simply not be announced
yet. Without this flag, `ex_dates: []` is ambiguous between "no dividend" and "not
knowable", and Phase 2 would read the second as the first — silently treating an
unflagged contaminated window as clean. **An absent flag must never be read as an
absence of dividends.**

Phase 2 then has two admissible strategies, and the manifest supports both:

- **Exclude** windows where `ex_dates` is non-empty, or where `known` is false and
  the ticker pays dividends at all.
- **Add the dividend back** at scoring time: compare the forecast against
  `realised_move + total_amount / spot_price`.

The authoritative determination is Phase 2's, not Phase 1's, because after the
window has elapsed the ex-dates are simply historical fact. Phase 1's obligation
is narrower and absolute: **record the window bounds and what was knowable, so
Phase 2 can ask the question at all.**

## Consequences

- One more provider surface — `DividendSource` — and it is allowed to fail. A
  dividend lookup that cannot answer sets `known=false` and the run proceeds; a
  forecast is not blocked by an unavailable dividend calendar.
- Stooq publishes no dividend data, so a run served by the Stooq fallback will
  usually carry `known=false`. That is correct and visible rather than silently
  clean, and it is one more reason the serving provider is in the manifest.
- **Phase 2 must treat `known=false` as "unknown", never as "none".** This is the
  single obligation this ADR creates and the one place it can be got wrong.
- Zero-dividend tickers cost a lookup that always returns empty. Acceptable.
- If Phase 2 later wants total-return scoring, the dividend amounts recorded here
  are already what it needs; the basis would not have to change.
