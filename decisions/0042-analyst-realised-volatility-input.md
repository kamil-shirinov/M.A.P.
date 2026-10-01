# 0042 — An optional realised-volatility input to the analyst (experiment A2), off by default

**Status:** accepted, mechanism only — **built, not run** · **Date:** 2026-10-01 · **Builds on** [0016](0016-five-day-horizon.md) · [0026](0026-forecast-digest.md) · [0029](0029-freeze-digest.md)

## Context

Phase 5's experiment A2 asks whether the analyst does better when it is told how much
the stock has recently moved. The measured reason to ask is that the system's
volatilities span about half the cross-sectional range of a trailing-volatility baseline
(`docs/results.md`, records 5–8), and on the development half the system loses to that
baseline on CRPS by 5.4%. Nothing in the pipeline gives the analyst the figure today:
the only trailing volatility in the repository is in `mapf.eval`, which scores a forecast
and does not make one.

**[ADR 0016](0016-five-day-horizon.md) rejected this once, and the rejection stands for
the system it was made about.** It said passing trailing volatility as a prompt slot
"would hand the model the random-walk baseline, and beating a baseline you were given is
not a measurement." That is the constraint A2 has to live inside, not one it removes: A2
is a different system, labelled as one, whose result can never be read as "M.A.P. beats
the random walk". The pre-registration says so in terms.

Two further constraints from the frozen record:

- **The frozen system must be untouched, down to the template's hash.** The corpus runner
  verifies the freeze by comparing the *frozen* templates' hashes. A change that
  re-versioned `scenario_analyst` would fail it; one that merely added a code path would
  pass it while running something else.
- **The pipeline cannot import `eval`.** `eval` is excluded from the forecast digest on the
  ground that no forecast depends on it ([0026](0026-forecast-digest.md)). A pipeline that
  imported it would make that exclusion untrue.

## Options

1. **A slot in `scenario_analyst.v3`.** Rejected: it changes the frozen template's hash, and
   with it every cache key the corpus produced.
2. **`scenario_analyst.v4` with the slot, chosen by `[prompts] analyst = "v4"`, and a
   second switch for computing the figure.** Rejected: two settings that must agree. Set
   one and not the other and the run is the control, or fails after a model has been paid
   for.
3. **A separate template name, chosen by one switch, with the figure computed where the
   window already is.**

## Decision

**Option 3.**

- **`[experiments] analyst_realised_vol = false`** in `config/default.toml`. Off is the
  frozen system: the same prompt bytes, the same cache keys, the same forecasts.
  A test renders the off path and compares it to the store's `scenario_analyst.v3`, and
  checks that v3's hash equals the one in `corpus/frozen.json`.
- **On** selects `scenario_analyst_vol` at `[prompts] analyst_realised_vol` (`v1`), in one
  branch in `build_run`, so the template and its version cannot disagree.
- **`scenario_analyst_vol.v1` is `v3` plus two lines**, and a test fails if it is ever
  anything else:

  ```diff
  -**1. Use only the facts provided.** Your reasoning must rest on the untrusted-data block below and nothing else. …
  +**1. Use only the facts provided.** Your reasoning must rest on the untrusted-data block below and the realised-volatility figure given with it, and nothing else. …
   Forecast horizon: {{horizon_days}} trading days
  +Trailing realised volatility of {{ticker}}: {{realised_vol}} (annualised, from its daily closes before the date above; a measurement of the past, not a forecast)
  ```

  The first line had to change: rule 1 says reasoning rests on the block and nothing else,
  and a figure outside the block would contradict it. That makes the prompt confound two
  lines, not one, and the pre-registration states it.
- **The figure** is the sample standard deviation (ddof = 1) of daily log returns over the
  run's own settled closes **strictly before the anchor session**, times √252, shown to two
  decimals — `mapf.core.volatility`. Strictly before is the random-walk baseline's own
  information set (`History.before(as_of)`), and a test pins the two estimators to each other
  because they live on opposite sides of the `eval` boundary. It is a trusted slot: it is
  computed here from prices, not read from a feed. It is not a calibrated quantity and is
  not rescaled to the horizon; it is annualised because the forecast's own `vol` is, so no
  conversion sits between what the model is shown and what it writes.
- **No new data call.** It comes from the window `execute` has already fetched and trimmed,
  so every price read still goes through `data/providers`.
- **A window too short or flat to give one fails before any model runs**
  (`InsufficientVolatilityHistoryError`, at least 60 returns, the baseline's own floor). It
  is never run without the figure and counted as an A2 item.
- **A mismatch is refused both ways** (`AnalystInputError`): a figure handed to a template
  with no slot, and a template with a slot given none.
- **`execute` refuses an analyst that takes the figure unless the run has an `arm` label.**
  Every path — the corpus runner, `map run`, the ablation — goes through `execute`, so this
  is the one place a run with the switch on cannot be mistaken for the frozen system. The
  corpus runner passes no arm; with the switch on it fails on the first item rather than
  writing A2 forecasts to the ledger under a freeze that vouches for different prompts.
- **`scripts/ablation.py` gains arm `A2`**, which turns the switch on through the
  settings it builds and passes its own name as the arm.

## Consequences

- **`forecast_digest` moves** for any run made after this change: it hashes every file
  under `config/` and `src/mapf/` that can produce a forecast, and this touches eight of
  them, six edited and two added ([0026](0026-forecast-digest.md), "the granularity is a file"). So did
  [0039](0039-live-prices-in-the-local-app.md). What the freeze governs — the templates'
  hashes, models, sampling — is unchanged, which is the part a test checks, and
  `freeze_digest` is therefore unaffected.
- **Nothing here has run a model**, and nothing in the experiment has been measured. What
  is tested is the wiring: that off is byte-identical, that on shows the figure, which
  closes it is computed from, and the refusals.
- **The `ungrounded_numerals` check is not comparable across A and A2.** It flags a figure in
  a justification that traces to no material fact, and the volatility figure is not in the
  facts. An A2 justification that quotes it will be flagged. `core/quality.py` is not changed:
  the check is part of the frozen system, and a counter that moved with the experiment is a
  measurement that moved.
- **The window a run reads is whichever the price cache holds**; the figure it produces is
  recorded in the run's trace (the rendered prompt) and nowhere else. See the
  pre-registration's open question on the price vintage.
- **A2's result is a statement about A2.** It cannot support "the system beats the random
  walk", because the random walk's volatility was in the prompt.
