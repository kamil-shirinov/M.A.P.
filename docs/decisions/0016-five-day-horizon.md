# 0016 — The forecast horizon is five trading days

Status: Accepted · Date: 2026-08-13 · Phase 2

## Context

21 days was the Phase 1 default and had never been justified — it arrived by
inheritance and was about to be frozen into panel construction, where it is
expensive to revisit. Tested before freezing, at no inference cost.

## The statistical case is neutral, and that must not be misremembered

**Power is horizon-invariant at fixed compute.** Both the signal and the noise
scale with the window's volatility, so a shorter horizon buys nothing statistically
at the same number of forecasts:

| horizon | power at rho=0.20 | power at sigma x0.5 | power at sigma x2.0 |
|---|---|---|---|
| 5 | 19% | 74% | 99% |
| 10 | 14% | 78% | 97% |
| 21 | 26% | 80% | 93% |

Flat within simulation noise. **The case for five days is mechanical, not
statistical**, and this is recorded explicitly so that nobody later reconstructs it
as a power argument and draws the wrong lesson from it.

## The mechanical case

| horizon | sigma over window | max dates/ticker (2y) | P(ex-dividend in window) |
|---|---|---|---|
| 5 | 0.035 | 99 | **8%** |
| 10 | 0.050 | 49 | 16% |
| 21 | 0.072 | 23 | **33%** |

**A third of all 21-day windows contain an ex-dividend date.** Four payments a year
against 21 of 252 trading days is 33% by arithmetic, and the simulation measured
the same. ADR 0013 requires those windows excluded or separately reported, so the
21-day horizon costs a third of the reportable sample *before anything is scored* —
118 down to 79, against 109 at five days. Power to detect a 2x calibration error
after exclusion: 94% / 87% / 87%.

Losing a third of the sample silently to an obligation we imposed on ourselves is
the decisive argument.

The second column is the other half of it: at five days a two-year calendar yields
99 non-overlapping windows per ticker rather than 23.

**One argument deliberately not claimed.** Post-earnings announcement drift is
documented at 5-10 days, so true skill may be larger there. The simulation takes
skill as a parameter and can say nothing about whether it is real. That case rests
on the literature and is not evidence produced here.

## Decision

**Five trading days.**

### Horizon and worked-example scale are coupled and must move together

The v2 analyst template's worked example is `return=+0.06`. That is 0.83 sigma over
21 days and **1.70 sigma over five**. Left unchanged, the model would anchor on
21-day magnitudes inside a 5-day window — the units failure of 2026-08-12 in
different clothes, arriving through the example rather than the field name.

So `scenario_analyst.v3.md` ships in the same change as the horizon, with:

- the worked example rescaled to `+0.03` (0.83 sigma at five days)
- "a percent" rescaled to "half a percent"
- an explicit statement that **`vol` is annualised and does NOT rescale** — the
  trap inside the fix, since rescaling both would be the same error inverted

**Any future horizon change must re-version the analyst template.** The coupling is
invisible from the config, which is why it is written here and in `config/default.toml`.

A tempting alternative was rejected: passing the stock's trailing volatility as a
slot so the template could be horizon-agnostic. **That would hand the model the
random-walk baseline**, and beating a baseline you were given is not a measurement.

### The freed calendar is for stratification, not for a bigger panel

99 windows per ticker instead of 23 means date selection is no longer constrained
by the post-cutoff span — which was the constraint that forced 30x8. That freedom
should be spent on **temporal stratification and pre/post-cutoff balance**, not on
keeping the old panel shape or on simply buying more forecasts. Corpus construction
inherits a choice here rather than a constraint.

## Consequences

- CLI default horizon is 5; `PanelDesign.horizon_days` is 5.
- `scenario_analyst.v2.md` is kept. It is the record of what produced the 21-day
  runs, and deleting it would make those unreproducible.
- Absolute CRPS values shrink with the horizon (sigma 0.035 against 0.072), so
  scores are not comparable across horizons. Any comparison must hold it fixed.
