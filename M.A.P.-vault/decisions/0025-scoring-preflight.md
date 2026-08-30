# 0025 — A structural pre-flight for scoring

**Status:** accepted · **Date:** 2026-08-30 · **Builds on** [0019](0019-corpus-execution-protocol.md), [0022](0022-guard-scope.md), [0023](0023-scoring-adapters.md), [0024](0024-repeat-rule.md)

## Context

`map evaluate` had never seen a real artifact. Every test drove it against generated
series and synthetic forecasts, which is what keeps the suite offline and fast — and
which means the first real forecast it ever read would have been read on night six,
at the end of a twelve-night run, in the place where a crash costs most.

`map corpus run --check` exists for the same reason one layer down. This is its
counterpart.

## Decision

**`map evaluate --check`.** It loads from the ledger, applies every refusal, fetches
the realised windows, fits all three baselines, and confirms each completed item is
scoreable end to end — then prints **counts and reasons only**.

### It computes the scores and does not show them

The boundary is on what is *reported*, not on what is *run*. A pre-flight that
stopped short of the computation would be checking a different path from the one it
exists to protect, and the bug it missed would be in the gap.

Same separation the corpus runner already holds between health and result
([ADR 0019](0019-corpus-execution-protocol.md) §7): the runner computes forecasts for
twelve nights and prints no score, so nothing it shows can inform the decision to
continue. Here the scores exist in memory and reach no terminal.

### It reports every problem, not the first

A pre-flight that aborted on the first refusal would have to be run once per problem.
Under `--check` each refusal collects a line and continues; the exit code is non-zero
if any collected.

**This is where the design earned itself twice.** Making refusals continue exposed
two latent bugs immediately:

- The freeze-version block reported a mismatch and then unpacked `most_common()` into
  a single name — unreachable while the refusal raised, a `ValueError` the moment it
  did not.
- `require_one_vintage` raised from inside `score_band`, so a mixed vintage ended the
  pre-flight before it could report anything else.

Both are the same class: **code that is correct only because an earlier line always
throws.**

### Two checks are skipped, and named where they are skipped

- **The pass boundary is reported, not enforced.** An unfinished band is the normal
  case for a pre-flight; enforcing it would make the check unusable for exactly the
  situation it exists to serve. A scoring run still refuses.
- **Leakage is not computed.** It needs both bands, and an estimate on a half-finished
  band is a different number rather than a preliminary one.

### `strict=False` on `score_band`, and why it is not a hole

`require_one_vintage` is public and called by `score_band` unless `strict=False`. The
one caller passing `False` **runs the same function itself** and reports the result —
the check is moved, never skipped. Default-on, one implementation, no path that scores
a mixed band by forgetting.

## What it found on the first real run

35 completed items of the live clean band. **The path runs end to end: 35 of 35
scoreable, one vintage, all three baselines fitted on all 35.**

**The earnings-calendar decision is vindicated by the numbers.** EDGAR returned
**13–25** Item 2.02 dates per ticker over the lookback window; corpus membership would
have supplied 3–6. The multiplier was fitted on **35 of 35 items with 0 neutral** — so
the earnings baseline genuinely widens for a scheduled event on every item rather than
collapsing into the random walk under a second name ([ADR 0023](0023-scoring-adapters.md)).

**Both sensitivity partitions are non-empty and correct**, the direct refutation of the
defect in [[../Findings & Incidents#27]]:

| partition | members |
| --- | --- |
| truncated exhibits (ADR 0020) | BXP 2026-01-29, FCX 2026-01-23 |
| degeneration retries (ADR 0021) | FCX 2026-01-23, STZ 2026-01-08 |

STZ and FCX are the two items diagnosed as decoding loops in
[ADR 0021](0021-degeneration-retry.md), and both were **rescued by the retry** rather
than failing. FCX appears in both partitions, exactly as that ADR predicted.

**One problem, and it is the one worth finding now:** the band spans two commits.

## The unresolved consequence: mixed code is now structural

`318250ff9703` and `0d7832667133` both produced items of this band, because development
continued while the corpus ran. That will not stop — by night six the band will span
every commit made during it.

**`--allow-mixed-code` will therefore be required on every scoring run, which makes the
guard vacuous.** A check that must always be overridden never fires, which is the
failure of [[../Findings & Incidents#27]] arriving from the other direction.

The distinction the guard *wants* is already visible in these two commits:

- `318250ff9703` touched only scoring-side code. It **cannot** have changed a forecast.
- `0d7832667133` touched `pipeline/run.py`, `pipeline/manifest.py`, `core/quality.py`. It can.

So the question is not "which commit" but "did anything a forecast depends on change".
A **forecast digest** — a hash over the files that can produce a forecast, recorded in
the manifest beside the commit — answers it exactly, and two runs with the same digest
are forecast-equivalent however many commits separate them.

**Built in [ADR 0026](0026-forecast-digest.md).** The claim above that it "cannot be
computed retroactively" was wrong: the digest is a pure function of file contents at a
commit, and every manifest already records the commit — so `git ls-tree` recovers it
exactly for any clean-tree run. The 37 items already written were backfilled.

## Consequences

- The pre-flight makes one EDGAR request per distinct ticker. At 34 tickers that is
  ~5 s of traffic at 8 req/s, against a corpus run averaging ~0.003 req/s because it
  spends ten minutes per item in inference. Combined peak stays under EDGAR's 10/s,
  and the calendar is cached afterwards so a scoring run does not refetch.
- Sensitivity **membership** is named under `--check` while the comparison is not.
  Membership is structural; a partition reported only as a count cannot be checked
  against the ledger, and an empty one reads as reassurance.
