# 0031 — A required `--split`, and a holdout spendable exactly once

**Status:** accepted · **Date:** 2026-09-01 · **Committed before any forecast was scored** · **Builds on** [0019](0019-corpus-execution-protocol.md), [0026](0026-forecast-digest.md), [0027](0027-halt-response.md), [0030](0030-code-boundary-adjudication.md)

## Context

The frozen corpus carries a `dev` / `holdout` split, pre-registered at freeze time. Its
purpose is Phase 3: calibration is fitted on `dev`, and the holdout is the one sample
that can tell whether the fitted correction generalises or was tuned to the noise it was
fitted on. That test is only worth running **once**. A holdout looked at twice is a
development set with a more impressive name.

Until now nothing enforced this. `map evaluate` scored whatever the ledger contained,
and the split existed only as a field. The protection was an intention held by the one
person who most wants to see the number.

This is the third time in this project the same shape has appeared: a rule that held
because someone remembered it, until they did not. `verify_freeze` compared a subset of
the fields it claimed to compare; the trace guard checked a file existed but not what was
in it. Both were found by asking what a name verifies rather than what it implies. The
answer here was *nothing at all*, so the guard is written before the first score rather
than after the first regret.

## Options

**1. Report selectively.** Score everything, print only `dev`.
Rejected. A holdout item that reaches `score_band` produces a number, and a number that
has been computed in this process has been seen — by the model writing the summary if not
by the user. Filtering the display leaves the holdout's results in memory, which is
exactly what not spending it is meant to prevent. The filter has to sit at **load**.

**2. `--split` with `dev` as the default.** Rejected. A default is a decision made by
whoever forgets to pass the flag. The holdout must never be scoreable by omission, so the
option is **required and has no default** — the command refuses to run without an explicit
choice, and choosing `holdout` is then a deliberate act that leaves a record.

**3. A note in the README.** Rejected for the reason above: it is the intention, restated.

## Decision

**`--split` is required, filtering happens at load, and spending the holdout is recorded.**

- `load_band(ledger, corpus, runs_dir, band, split)` filters to the tickers the frozen
  corpus assigns to that split. Membership is still checked against the **whole** plan, so
  an item absent from both splits is refused rather than silently dropped (see below).
- A split no ticker carries is refused rather than returning an empty result. Zero items
  scored cleanly reads as *"nothing was wrong"*; it should read as *"you asked for
  something that does not exist."*
- Scoring `holdout` appends one line to `corpus/holdout_spend.jsonl`: the date, the band,
  the item count, the commit, the forecast digest, the freeze version and digest, and
  **which calibration artifact was in place** — currently `null`, and it says so rather
  than omitting the field.
- Any later holdout run refuses against that record, exit code 9.
- **The file is committed.** The git history is then the proof it was spent once, in the
  same way the frozen-corpus commit is the proof the corpus was pre-registered. An absence
  is checkable by anyone; a promise is checkable by no one.
- `--check` spends nothing, because it prints no score.

### The spend is recorded *before* any number is printed

The ordering is the whole mechanism. The holdout is spent when its results are **seen**,
so the failure to guard against is a run that computes the scores, dies between computing
and displaying, and leaves the ledger looking untouched. Erring that way lets a repeat be
justified as *"the last one didn't finish"* — which is true, and still a second look.

Erring the other way costs a holdout that was never actually read. That is the cheaper
error, and it is the one this takes.

## Consequences

- The holdout cannot be scored by accident, by omission, or twice, and the enforcement is
  a file rather than a habit.
- **A crash after scoring burns the holdout.** Accepted, deliberately, per the argument
  above. There is no override flag; unspending it would require editing a committed file,
  which is exactly the visible act it should be.
- Phase 3 must fit calibration on `dev` alone and decide it is finished **before** the
  holdout is touched. The spend record's `calibration` field is what makes that
  auditable after the fact: a holdout scored with `calibration: null` is a holdout scored
  before there was anything to test, and the record says so permanently.

## The bug this found on the way in

Writing the split filter, I restricted the completed set by split *before* checking corpus
membership. A ledger item naming a ticker the frozen corpus does not contain at all then
stopped being refused — it was neither in this split nor in the other, so it fell out of
both branches and vanished. An existing test caught it.

The guard was not weakened by anyone editing the guard. It was weakened by a filter added
upstream of it for an unrelated reason, and only the test standing behind it noticed. That
is the second instance this week of the same lesson: *the thing that protects a check is
not the check's own code.*
