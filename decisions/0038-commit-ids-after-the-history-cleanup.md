# 0038 — Commit IDs after the history cleanup: records keep theirs, one map resolves them

**Status:** accepted · **Date:** 2026-09-30 · **Follows** Findings #58 and #71

## Context

The history cleanup of 2026-09-30 (Findings #71) gave every commit a new ID. It had to:
the first commit changed, and a commit's ID covers its whole ancestry. Commit IDs are
written into things that are not edited after the fact — ADRs, Findings, the git notes,
commit messages, `corpus/holdout_spend.jsonl`, the scoring records and the run manifests
under `var/`, and every export made so far. The holdout spend record already named a
commit the published history did not hold, after the 8 September rebase (#58), and the
holdout page handled that one case with a one-entry table.

Four places on the app's pages show a commit: the holdout's terms (its `commit` and the
`prereg` text), a scoring record's identity line, the company footer's `code` stamp, and
one disclosure sentence that cites the pre-registration's commit.

## Options

1. **Edit every citation to the new IDs.** Rejected: it edits records, which this project
   never does, and it would have to be repeated for `var/` and every export on every
   machine that holds one.
2. **Translate in the export.** `map export` writes a resolved ID beside each recorded one.
   Rejected as the only mechanism: it helps only once an export is regenerated, and it
   cannot reach an ID written into page text.
3. **One map, resolved where an ID is shown.** `docs/commit-map.tsv` pairs every old ID
   with its new one; the app imports a copy and resolves every commit it shows. Records and
   exports stay as written.

## Decision

**Option 3.**

- `docs/commit-map.tsv` is the record: `old`, `new`, `kind`, `via`. It has 276 `commit`
  rows, 22 `note` rows for the notes appends, and 25 `rebased` rows for the originals the
  8 September rebase replaced. Those resolve straight to the new ID of their published
  copy, and `via` names the copy. Old IDs are unique to seven characters, and no new ID
  shares seven characters with an old one.
- `ui/assets/js/data/commit-map.js` is a copy of its `commit` and `rebased` rows that the
  browser can import without an export. `ui/tests/commits.test.mjs` fails if the two
  disagree.
- `ui/assets/js/lib/commits.js` resolves an ID to `{shown, recorded, event}`. A page shows
  the published ID and keeps the recorded one visible beside it: two rows on the holdout
  card, as that card already did, and "recorded as …" inline elsewhere. An ID the map does
  not know is shown as written, and nothing is invented for it. That covers everything
  recorded after the cleanup, which already names a published commit.
- A test fails if any page's code names an old commit other than through the resolver.
  Comments are exempt, because they cite commits the way records do.
- Code that **executes** against an ID uses the new one: the two tests that `git show` a
  past freeze, and the README's `git notes show` command. An instruction that fails on the
  published history is broken, not historical.

## Consequences

- A reader can take any ID from any record and find its commit, in one file, without
  either ID being edited away.
- The export's `--check` reports `code.commit` as moved for any export made before the
  cleanup. That is correct: the checkout names a different commit. Re-exporting clears it.
- On the machine that made the records, the old commits stay resolvable through local
  refs under `refs/archive/`, so `map evaluate`'s refusal messages, which `git diff` two
  recorded commits, keep working there. Nowhere else needs them.
- The map is fixed. A further rewrite would need a second map, or a chain like the one the
  `rebased` rows already are.
