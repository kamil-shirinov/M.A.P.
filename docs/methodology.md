# Methodology

How the corpus was built, what the scoring rules are, and what the baselines do.
The decisions behind each are in [decisions/](../decisions/).

---

### How 10,398 tickers became 120 companies

Every narrowing below is a recorded artifact, not a description written afterwards.

| | count | what removed the rest |
|---|---|---|
| Tickers in the SEC index | **10,398** | — |
| Distinct filers behind them | **7,998** | 2,400 are share classes and dual listings of the same CIK |
| Filers with an Item 2.02 8-K in their recent block | **4,325** (54.1%) | 3,673 publish no earnings 8-K: funds, trusts, dormant registrants |
| Tickers belonging to one of those filers | **5,309** (51.1%) | — |
| Tickers examined by the seeded selection walk | **1,181** | the walk stops once the target is met; 6,478 were never reached |
| **Companies accepted into the frozen corpus** | **120** | 716 illiquid, 324 no price history, 19 no exhibit, 2 duplicate CIK |
| Filings held for them | **709** | — |
| Filings with a completed run | **701** | 8 failed terminally, and are exported with an empty run list rather than dropped |

The 54.1% is measured, not estimated: `scripts/edgar_prescreen.py` walked all 7,998
filers on 2026-09-09, one request each, and wrote `var/filers/item_202.jsonl`. An
earlier name-keyword guess at the same question was wrong about **15%** of what it
flagged — "Trust" and "Shares" are as common in REITs and banks as in funds.

Two numbers in that table are easy to misread. **1,181 is not a rejection rate**: the
selection walk stops when it has enough companies, so the 6,478 unreached tickers are
untested rather than failed. And **709 versus 701** is why the export carries every held
filing with an explicit run list, empty where nothing ran — a page showing 701 would
misstate the corpus it is drawing.

---

## A documented property: the probability-weight tolerance

Scenario weights must sum to `1.0`. They are checked with a tolerance of `1e-6`
rather than for equality, and the tolerance is load-bearing — not a convenience.

Three decimal weights are not exactly representable in binary, so the sum depends
on the order the branches are added:

```
0.1 + 0.2 + 0.7  ==  1.0
0.2 + 0.7 + 0.1  ==  0.9999999999999999
```

An equality check would accept or reject the same forecast depending on which
branch happened to be added first. The error here is ~1.1e-16, far inside the
tolerance, so behaviour does not actually change — but it shows why the tolerance
has to exist.

The tolerance also has an **asymmetric boundary**, and this is worth stating
plainly because it looks like a bug and is not:

```
0.25 + 0.60 + 0.150001  →  |sum - 1| = 9.99999999917733e-07   accepted
0.25 + 0.60 + 0.149999  →  |sum - 1| = 1.00000000002876e-06   rejected
```

The same nominal deviation of `1e-6` is accepted above `1.0` and rejected below
it. Neither computed value *is* `1e-6`; both are the nearest representable double,
and they land on opposite sides of the comparison. This is a property of binary
floating point, not of the validator, and it cannot be tuned away — **any**
threshold has an edge that behaves this way. Moving to `math.isclose` would
relocate the asymmetry, not remove it.

Both properties are pinned in `tests/unit/test_scenario_validators.py`, so a change
to the comparison shows up as a failing test rather than as a silent shift in which
forecasts are accepted. No other test depends on the exact boundary.
