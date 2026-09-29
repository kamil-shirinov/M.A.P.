# 0037 — Continuous integration: the gate runs on every push

**Status:** accepted · **Date:** 2026-09-29 · **Builds on** [0004](0004-import-boundary-enforcement.md) · **Closes** the open question in Findings #65

## Context

The gate is six commands: `ruff check`, `ruff format --check`, `mypy`, `lint-imports`,
`pytest` and the node suite. `docs/setup.md` listed them, and the definition-of-done test
kept the linters out of pytest on the grounds that they run "in the same command that runs
this suite" — in CI. There was no CI. In practice the push gate was the two test suites,
run by hand, and two things got past it:

- an import contract broken on `main` for one commit, because nothing ran `lint-imports`
  (Findings #65);
- 39 `mypy` and 8 `ruff` errors across three test files, found on 2026-09-29, because
  nothing ran either tool.

Setting CI up exposed a third. Run on a clean clone, two export tests failed and one
front-end test crashed, because each read a gitignored file that exists only on the
machine that made it (Findings #67). A hand-run gate on that machine could never see it.

## Options

1. **Run the linters inside pytest.** One command, no new infrastructure. Rejected for the
   reasons the definition-of-done test already gives: slow, duplicated, and failing for
   reasons unrelated to the code under test. It also fixes nothing about *when* the gate
   runs — it still runs only when someone runs it, on a machine that has every
   gitignored file.
2. **A local pre-push hook.** Catches the first two cases. It is per-clone, bypassable
   with `--no-verify`, not versioned unless `core.hooksPath` is set by hand, and runs on
   the same machine with the same untracked files, so it cannot catch the third.
3. **A hosted workflow on every push.** A fresh checkout each time, so it sees what a
   stranger sees. Costs minutes on a private repository and adds third-party actions.

## Decision

Option 3: `.github/workflows/ci.yml`, GitHub Actions, on every push to any branch.

- **Two jobs.** `python` installs with `uv sync --extra dev --locked` and runs ruff,
  ruff format, mypy, lint-imports and pytest, in that order, so the fast checks fail
  first. `ui` runs `node --test ui/tests/*.test.mjs`. They run in parallel and fail
  separately.
- **Exactly as the suites are designed to run.** No models: pytest runs on
  `FakeProvider` with network tests deselected, which is the definition-of-done
  criterion 6. No export: the front-end tests that need `ui/assets/export/` skip with
  their reason. On a clean checkout that is **100 of 218 node tests run and 118
  skipped**. CI cannot see the export-dependent half; the hand-run gate on a machine
  with a full export still has to.
- **Pinned.** Each action is pinned to a commit SHA with its release in a comment:
  `actions/checkout` v7.0.1, `astral-sh/setup-uv` v10.2.0, `actions/setup-node`
  v7.0.0. A tag can be moved to different code; a commit cannot. uv is pinned to
  0.12.3 and Python to 3.12, matching `pyproject.toml` and the lockfile. The job has
  read-only repository permissions.
- **Linux, not macOS.** Development is on an M1. Ubuntu runners are cheaper and are a
  second platform: a case-sensitive filesystem and a UTC clock. The suites were run
  under `TZ=UTC` on a clean clone before the workflow was committed.
- **Pinned in a test.** `test_ci_runs_every_command_of_the_gate` asserts the workflow
  runs all seven lines, so removing one means changing that test too.

**The hand-run gate stays.** CI catches what gets past it; it does not replace it. A
push is still preceded by all six commands locally.

## Consequences

- The definition-of-done test's claim that the linters run in CI is now true.
- A red run on `main` is visible on the repository and in the commit's status. Nothing
  blocks a push on it. Branch protection is not available for a private repository on
  this account's plan — the API answers 403 — so CI reports and does not gate.
- The front end's export-dependent assertions remain a local-only check. Committing an
  export to make them run in CI was not considered: the export is derived, 5 MB, and
  carries third-party price data (`.gitignore`).
- Actions minutes are billed against the account's private-repository allowance.
- Bumping an action means resolving its new release to a SHA, not editing a tag.
