# Experiment A2 — pre-registration, DRAFT

**This is not a record.** A pre-registration here is a git note, appended locally, whose
commit date on the notes ref is the evidence that it preceded the result
([README](../README.md#verify-it-yourself)). This file is a draft for review. Nothing in it
has been run: no model was called to write it, and the mechanism it describes
([ADR 0042](../decisions/0042-analyst-realised-volatility-input.md)) was tested only with
scripted responses.

It becomes a record when you append it as note 23. That is a step for your laptop, and the
first A2 inference must come after it.

---

## For review — not part of the record

### Decisions that are yours, and that I have drafted a position on

These are the places where the draft chooses and the choice could reasonably go the other
way. Each is worded in the record below as drafted; change the record, not just this list.

1. **The sample is all 355 development items, both bands pooled — not a subsample.** It is
   the sample arm A already has, so every comparison is paired. The price is analyst
   generation on every item: at the 5,585-token mean in record 15 and 12 tok/s (the
   config's conservative floor; 16.0 was measured warm), about **46 hours**; 37–69 hours
   across 15–8 tok/s. A seeded 120-item subsample
   (record 15's own execution seed) would be about a third of that and would lose power the
   design is already short of. I chose the full set.
2. **No holdout is touched.** `corpus/holdout_spend.jsonl` records one spend, the **clean**
   band's, on 2026-09-05. It records none for the **ambiguous** band; I did not check what
   `map evaluate --split holdout` does with that band, so whether it is still unspent is
   for you to confirm. The draft treats A2 on the development half as **development
   evidence** and says so, because that half generated the compression finding A2 is
   motivated by. A confirmatory run on a holdout would need its own registration, and
   spending a holdout on a hypothesis that was itself shaped on development is a decision I
   have not made for you.
3. **There is one primary comparison, and it is A2 against A.** Not A2 against the random
   walk (see below), and no second primary, so no multiplicity correction.
4. **The re-derivation control (record 20) is used as a yardstick, not a gate.** Record 20
   removed the control's gating role *for arm B* and stated that re-purposing a gate after
   the fact is not legitimate. Reinstating one for A2 would be exactly that, so the draft
   reports the control beside the A2 result and does not condition on it. If you want a
   gate, it needs to be written here, now, with its estimator.
5. **The figure is shown to two decimals, annualised, over the whole fetched window.** That
   is about 500 sessions (the 730 calendar days `history_days` asks for), which is what the
   random-walk baseline fits on. It is a long-run estimate, not a recent one — "trailing" in
   this project's sense, and not a 20- or 60-day figure. A shorter window would be a
   different experiment, and adding it as an option adds a degree of freedom, so the code has
   no such option.

### Things I could not establish from the cloud session

- **Which price vintage each A2 item's window comes from.** `scripts/ablation.py` builds its
  market data without pinning a vintage, so it reads whatever the cache holds on the day of
  the run. The 2026-09-05 snapshot holds the *scoring* windows, not the 730-day run windows,
  and the corpus runner's `prices.fetched_on` is a label rather than a pin (notebook STATE,
  "open questions"). Split-adjustment multiplies a whole history by one factor and leaves
  daily returns alone, so this matters only where a provider's adjustment lands late, as it
  did for SCCO. The draft handles it by recording the figure as shown and reporting the ratio
  to the baseline's σ (S5). **You may want a pinned window, which needs looking at `var/`.**
- **Record 15's prior says "the document and the trailing volatility, both of which survive
  removing the analyst."** I found no trailing volatility anywhere in the forecast path (only
  in `mapf.eval`). If that sentence means the model's *memory* of the stock's volatility, it
  is the contamination trap in a new place, and it is why S4 splits by band. If it means
  something I have not found, A2 is not testing what the draft says it is.
- **The numbers in the record that I took from records 5, 8, 15, 17 and 20** are quoted from
  the notes ref as fetched on 2026-10-01, not recomputed.

### What changed in the repository, for the record's own claims

- `forecast_digest` moves for any run after this PR (every file under `config/` and
  `src/mapf/` that can produce a forecast is hashed — [ADR 0026](../decisions/0026-forecast-digest.md)).
  The part the freeze governs is unchanged, and a test pins it: with the switch off the
  analyst's prompt is byte-identical and `scenario_analyst.v3`'s hash is the one in
  `corpus/frozen.json`.
- The record below should be appended with the **commit hash** of the merged mechanism in
  its first lines, so that "what was run" is a commit and not a description.

### To append it (on the laptop)

Everything between the `text` fences below is the record. Fill every `<<…>>` marker
(`<<DATE>>`, `<<COMMIT>>` and the two `<<OPEN: …>>`). The commands refuse to append while a
marker remains:

```bash
git fetch origin 'refs/notes/*:refs/notes/*'
git notes show 171a4d6 | tail -n 3        # confirm you are appending to the same note
awk '/^```text$/{f=1;next} /^```$/{f=0} f' docs/preregistration-a2-draft.md > /tmp/record23.txt
! grep -n '<<' /tmp/record23.txt && git notes append -F /tmp/record23.txt 171a4d6
git log --format='%h %ad' --date=iso -1 refs/notes/commits    # the timestamp that matters
```

---

## The record

```text
RECORD 23 — EXPERIMENT A2 (trailing realised volatility as an input), PRE-REGISTERED
BEFORE ANY ARM RUNS
written <<DATE>>. No A2 inference has been performed. Mechanism: commit <<COMMIT>>,
ADR 0042.
=============================================================================

QUESTION. Does the analyst forecast better when it is told how much the stock has
recently moved?

  ARM A   the frozen system. 355 stored forecasts; replayed from cache in the ablation.
  ARM A2  arm A with ONE change: the analyst's template is scenario_analyst_vol.v1,
          and its prompt carries the stock's trailing realised volatility.

WHAT THE INPUT IS, FIXED NOW.
  The sample standard deviation (ddof=1) of daily log returns over the closes of the
  run's own settled window STRICTLY BEFORE the anchor session, times sqrt(252),
  shown to two decimals as an annualised decimal fraction. Strictly before the
  anchor is the random-walk baseline's own information set. The window is the
  730 calendar days the pipeline already fetches (about 500 sessions); at least 60
  returns are required, and an item without them FAILS and is reported, never run
  without the figure. There is no shorter-window variant.

THE CENTRAL FACT ABOUT THIS EXPERIMENT, STATED BEFORE ANY NUMBER EXISTS.
  The figure the analyst is given is, up to the window it was computed over, the
  random-walk baseline's own volatility. ADR 0016 rejected this design for the frozen
  system for that reason: beating a baseline you were handed is not a measurement.
  A2 is a different system and is read as one. NO RESULT OF THIS EXPERIMENT MAY BE
  REPORTED AS "M.A.P. BEATS THE RANDOM WALK". A2 vs the random walk is reported and
  carries no inferential claim in either direction.

SAMPLE. The 355 loaded development items, both bands pooled (349 scoreable: clean
175 + ambiguous 174, over 42 occupied 10-day blocks, as in record 15). Pooled for
the reason record 15 gave, and the bands are ALSO reported separately. THE
HOLDOUTS ARE NOT TOUCHED. This is development-half evidence only: the development
half is where the compression finding A2 is motivated by was found, so A2's result
on it is not a test of anything the data did not shape. A confirmatory run on any
holdout needs its own record, written before it.

PRIMARY. ONE comparison, no family, so no correction:
  CRPS(A2) - CRPS(A), paired by item, scored identically to every arm: vintage
  2026-09-05 pinned and read-only, realised bar pinned (keyed on ticker, as_of and
  horizon, not on the arm), the same three baselines.
  ESTIMATOR, written out because a threshold without one is not a pre-registration:
  mapf.eval.aggregate.compare, cluster-robust moving-block bootstrap, 10-day blocks
  (twice the horizon), 4000 draws, seed 20260813, 95% percentile interval, in the
  PINNED order (by day, then item id "TICKER YYYY-MM-DD"; Findings #70; the code's
  behaviour from b993512). The early records were computed in a different tie order
  and a new registration should not inherit it. "Better" means the interval lies
  wholly below zero.

SECONDARY, descriptive, no inferential use and not part of any family:
  S1  log score, paired, same estimator.
  S2  the volatility-compression statistics of records 6 and 8, unchanged, for A2 and
      for A on the same items: forward slope, reverse slope, Frisch bounds,
      attenuation-corrected slope (lambda from corr(log sigma_RW, log sigma_GARCH)
      on the same items), spread ratio.
  S3  P(up) span and median per arm.
  S4  every comparison above, by band, clean and ambiguous separately. The clean band
      is post-cutoff, where the model has less memorised about the stock's volatility.
      A gain that is larger there than on the ambiguous band is reported as such.
  S5  m_i = sigma_input,i / sigma_RW,i per item, where sigma_RW is the baseline as
      scored (its window is the scoring snapshot's, not the run's, so the two need not
      be equal). Report the distribution. It is what makes "the input is the
      baseline's volatility" a measurement and not an assumption.
  S6  COPY RATE: the share of items whose three scenario vols all lie within 0.02 of
      the figure shown, and the share whose base-case vol does. It separates "the
      model ignored the figure" from "the model used it".
  S7  A2 vs the random walk and GARCH, CRPS and log score, paired, same estimator,
      REPORTED AND NOT CLAIMED (see above).
  S8  the re-derivation control of record 20, beside the primary: the cold-minus-cached
      paired mean CRPS difference and its per-item SD on the 60-item subsample. A
      yardstick for how much of A2 - A could be a fresh draw rather than the input.
      NOT A GATE: record 20 removed that role and re-purposing it after the fact would
      be the researcher degree of freedom the record exists to refuse.

CONFOUNDS, ALL STATED UP FRONT.
  1. DRAW NOISE. A is a cached temperature-0.7 draw; A2 is a fresh one, and this
     backend honours the seed only partly (record 15: 2 of 5 replays byte-identical).
     A2 - A is the input's effect PLUS the difference between two independent draws.
     S8 sizes the second; nothing separates them.
  2. THE PROMPT CHANGE IS TWO LINES, not one: the figure's line, and rule 1, which said
     reasoning rests on the block "and nothing else" and had to admit the figure. The
     diff is in ADR 0042 and a test fails if it grows.
  3. THE MODEL'S OWN MEMORY. It may already know the stock's volatility from training,
     in which case the figure adds less than it appears to on well-known tickers. S4.
  4. WINDOW AND VINTAGE. The figure is computed from the window the cache holds on the
     day of the run, not from a pinned snapshot. It is recorded as shown, in the run's
     trace. S5 reports how far it sits from the baseline's. <<OPEN: pin the window?>>
  5. NOT COMPARABLE: the ungrounded-numeral count. The figure is not among the
     material facts, so an A2 justification that quotes it is flagged. Reported for
     both arms and not compared.

FAILURES. An item that fails in either arm is reported by name and cause and dropped
from the paired comparison in both. The count of dropped items is reported next to every
interval. An item dropped only for A2 because the window held fewer than 60 returns is
counted as such and not as a model failure.

PRIOR, stated before running. <<OPEN: this is mine to state, and the draft only
proposes it>>  The most likely outcome is that A2 CLOSES MOST OF A's GAP TO THE RANDOM
WALK and goes no further: on the clean development band (175 items) A is worse than
the random walk by 5.4% on CRPS and 12.9% on log score (3.9% on CRPS on the ambiguous
band), and its volatilities span about half the baseline's range, so a model told the
baseline's number is expected to move towards it. Giving the
model the number it was missing and finding it then does about as well as that number is
not evidence for the analyst. S2 is expected to move towards 1 largely by construction.

READING OF EVERY OUTCOME.
  A2 ~ A on CRPS (interval covers zero)
    Giving the figure does not measurably change forecast quality at this size. Use S6
    and S2 to say whether the figure was IGNORED (copy rate low, slope unmoved) or USED
    WITHOUT EFFECT (copy rate high, slope up, CRPS unmoved - which would show that
    compression was not what cost CRPS). Reported as "no difference larger than about
    2.5%", never as "no difference".
  A2 BETTER THAN A, and S7 shows A2 ~ the random walk
    The predicted outcome. The improvement is the baseline's volatility passed through.
    It says the system's compression was a real cost and that the analyst, with the
    number in hand, adds nothing the baseline lacks. NOT evidence for the architecture.
  A2 BETTER THAN A, and S7 shows A2 better than the random walk
    Unexpected. Reported prominently and not as a result: the development half shaped
    this hypothesis, S7 carries no inferential claim, and this outcome triggers a
    separate confirmatory registration, not a conclusion.
  A2 WORSE THAN A
    Giving the figure degrades the forecast, for instance by anchoring scenario
    dispersion to a long-run level at the moments it should differ most (an earnings
    window). Reported prominently and not explained away.
  SLOPE (S2) MOVES TOWARDS 1 WITH CRPS UNMOVED
    Compression was not what cost CRPS. A finding about the diagnosis, independent of
    whether A2 improves anything.
  BANDS DIFFER (S4)
    Reported as a measurement with its interval. The two bands hold different items, so
    each is resampled on its own days, as in the extra check of the leakage estimate.

POWER, stated in advance. At 349 items over 42 blocks the ablation could detect about a
2.5-3% difference in CRPS and could not detect 1% (records 15 and 17; half-width near
0.0008 against a mean near 0.032). THE GAP A2 IS EXPECTED TO CLOSE (about 4-5% of CRPS) IS ABOVE THAT;
a 1% effect is not. A null is a null about effects larger than about 2.5%.

COST AND RESUMPTION, so the run is not redesigned half way. Every A2 analyst call is a
fresh 12B generation: about 46 hours at 12 tok/s over 355 items. The run is resumable
(index.jsonl records successes only; a failure is retried on resume) and writes to
var/ablation/A2/, never runs/. NOTHING MAY BE CHANGED IN THE MECHANISM, THE TEMPLATE OR
THIS RECORD DURING THE RUN; a change is a new record and a new arm.

WHAT THIS DOES NOT DO. It does not calibrate, does not use a holdout, does not test
whether the analyst adds information beyond volatility, and does not change the frozen
system: with the switch off the analyst's prompt is byte-identical and its template hash
is the one corpus/frozen.json records.
=============================================================================
```
