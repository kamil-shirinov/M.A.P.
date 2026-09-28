# 0026 — Compare what a forecast depended on, not which commit produced it

**Status:** accepted · **Date:** 2026-08-30 · **Builds on** [0019](0019-corpus-execution-protocol.md), [0022](0022-guard-scope.md), [0025](0025-scoring-preflight.md)

## Context

`map evaluate` refused to score a band produced by more than one commit. The first
real pre-flight ([ADR 0025](0025-scoring-preflight.md)) showed the band already
spanning two, thirty-five items in — because development continues while a corpus
runs, and it does not stop for twelve nights.

So the guard would have needed `--allow-mixed-code` on **every** scoring run. **A
check that must be overridden every time is not a check** — it is [[../Findings & Incidents#27]]
arriving from the other side: there, a partition that could never fire read as
reassurance; here, a refusal that always fires trains you to wave it through.

The distinction it wants was visible in those two commits. One touched only
scoring-side code and **cannot** have changed a forecast. The other touched
`pipeline/run.py`, `pipeline/manifest.py` and `core/quality.py`, and can. The question
is not *which commit produced this item* but *did anything a forecast depends on
differ*.

## Decision

**A forecast digest**, recorded in every manifest beside the commit: a hash over the
contents of every file that can produce a forecast. Two runs sharing it are
forecast-equivalent however many commits separate them, and `map evaluate` compares
digests.

### How it is computed, and why that makes it recoverable

From `git ls-tree -r <commit>`, which lists each path beside its **blob hash** — and
a git blob hash is a hash of the file's contents. The digest is therefore a pure
function of the tree at a commit and of nothing else: not of the clock, not of the
machine, not of anything that was not written down.

**That is what makes the backfill legitimate rather than invention.** Every manifest
already records its commit, so the contents are recoverable exactly. It computes a
function of recorded data; it does not infer data that was never recorded. The second
would be the failure that made inferring a run's identity from timestamps wrong.

**A dirty-tree run stays `unknown`** and is excluded from the equality check, said
plainly. Its commit does not describe the files that ran, so no honest digest can be
taken from it — and it is counted apart rather than grouped with a clean run, because
grouping would assert exactly the equivalence that cannot be established.

### What counts as forecast-producing

Everything under `config/` and `src/mapf/` **unless it provably cannot**, with a short
exclusion list of modules that run strictly after a corpus and read its artifacts:
`eval/`, `render/`, `cli/commands/evaluate.py`, `corpus/forecasts.py`,
`corpus/passes.py`, `data/earnings.py`.

The bias is deliberate and one-directional: **over-including costs a false refusal,
which is visible and recoverable; under-including costs a false claim that two runs
are equivalent, which is neither.** A test asserts every exclusion sits inside an
included root, so an exclusion cannot name a path the digest never covered and read
as protection that is not there.

### The granularity is a file, and that is a real limitation

This answers *did any file that can produce a forecast change*, not *did the
forecast-producing behaviour change*. The second is undecidable without running both.

**It is already binding.** The band's two digest groups differ by exactly three files
— `config/default.toml`, `src/mapf/bootstrap.py`, `src/mapf/settings/loader.py` — and
the entire difference is the scoring-side earnings calendar: a config key, a settings
field, and a `build_earnings_calendar` function called only by `map evaluate`. None of
it can change a forecast. The digest splits the band anyway.

Tightening the exclusion list until that split disappeared would be choosing the rule
after seeing the result, which is the researcher degree of freedom this project spends
its effort refusing. So the split stands, and the answer is to make the override
informed instead of blind.

### The refusal carries its own evidence

When digests differ, `map evaluate` names the forecast-producing files that differ
between them:

```
code       3 distinct forecast digests produced this band:
           ef4c60c0c74a  22 runs
           fd5154ed7e9b  15 runs
           differs: config/default.toml
           differs: src/mapf/bootstrap.py
           differs: src/mapf/settings/loader.py
```

That turns `--allow-mixed-code` from a flag you learn to pass into a judgement you can
make in one glance — and it distinguishes the case above from one where
`pipeline/run.py` differs, which it should not wave through. The diff is evidence for
a reader and never the thing being decided: if `git` is unavailable the refusal still
stands, with no files listed.

## Consequences

- `manifest_version` goes to **1.6.0**. `CodeVersion` gains `forecast_digest`.
- **The 37 items already written were backfilled** by
  `scripts/backfill_forecast_digest.py`, which is idempotent, makes no network call,
  and rewrites each manifest atomically — a plain write interrupted part-way leaves a
  truncated manifest, and a truncated manifest is an item that cannot be audited or
  scored. It is safe to run while the corpus runs.
- **The backfill must be re-run as the band progresses.** The running process holds
  the pre-1.6.0 code in memory, so every item it writes until it restarts lacks the
  digest. Those are labelled `predates the digest` rather than folded into a group,
  which is what tells someone to run it again.
- Three labels are kept apart, because they are three different facts: `predates the
  digest` (recoverable — run the backfill), `+dirty (no digest)` (not recoverable, and
  excluded from the check), and `unknown` (no commit at all).
