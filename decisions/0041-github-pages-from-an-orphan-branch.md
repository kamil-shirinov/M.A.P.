# 0041 — Hosting on GitHub Pages from an orphan branch that holds only the site

**Status:** proposed — not deployed · **Date:** 2026-10-01 · **Builds on** [0036](0036-live-analysis.md) · [0039](0039-live-prices-in-the-local-app.md)

## Context

The repository is private and a clone cannot regenerate the export (`var/` is not
committed), so a reviewer who clones sees the No-export panel and nothing else.
`scripts/build_site.sh` already produces a servable directory, without the bulk price
series. What was missing is where it goes. Three constraints:

- **`main` must not carry the export.** It is derived, 3.7 MB, regenerated on every change
  to a run, and holds third-party market data; every deploy would otherwise be a commit
  on the branch the work is reviewed on.
- **Only the laptop can build it.** The export needs the ledger, the runs and the scoring
  passes.
- **The hosted copy has no server** (0036, 0039). The UI already answers an absent
  `health` as "no server", so a static host needs no change to it. Every URL it fetches
  is relative, which a project site served under `/<repo>/` requires.

## Options

1. **`docs/` or a build folder on `main`.** Rejected: puts the export on `main`.
2. **A Pages workflow deploying from `main`.** Rejected: the runner has no export.
3. **Another host** (Netlify, Vercel, `rsync`). Still possible on `site/`; none replaces
   history for free, and each adds an account and a credential to this project.
4. **An orphan `gh-pages` branch that holds only the built site, replaced on each deploy.**

## Decision

**Option 4, by `scripts/publish_site.sh`, run on the laptop.**

- The branch has **no shared history with `main`** and holds **one parentless commit**. The
  script builds it in a temporary repository and pushes `gh-pages:refs/heads/gh-pages`; it
  never switches the working clone, so there is nothing to stash and nothing to restore.
- **The branch name is a constant.** An option naming the branch is an option that can
  be given `main`.
- **There is no way to include prices.** The script calls the builder without
  `--with-prices` and then **verifies** instead of trusting: no `prices/`, the manifest says
  `prices.companies == 0`, nothing at the top level but pages, `assets/` and `robots.txt`,
  no parquet/jsonl/env anywhere. A refusal rather than a warning, because a published
  mistake cannot be recalled (below). A local home-directory path is a warning.
- **It publishes only a commit that is already on `origin/main`**, so the manifest's
  `forecast_digest` and the commit in the branch's message name something reviewable.
- **It asks.** Typing `publish` is required unless `--yes`; `--dry-run` does everything but
  the push.
- **The push is forced only against what it saw**: `--force-with-lease` on the commit it
  read from the remote a moment before, or a plain push when the branch does not exist.

## Consequences

- **The hosted site is public** whatever the repository's visibility, and Pages from a
  private repository depends on the plan. The repository being private protects the
  source and not this. Deciding whether the page should exist is the user's, and is
  listed in `docs/publishing.md` as the step before the first deploy.
- **The repository still carries the export, on `gh-pages`.** Anyone who can read it can
  read that branch; making it public later publishes the branch with it.
- **A force-push replaces the branch and does not recall it.** GitHub keeps unreachable
  commits retrievable by hash. A deploy that included something it should not have is
  not fixed by the next deploy, hence the refusals.
- **Prices left out removes the bulk series, not the third-party content** (1,556 closes,
  SEC rows), as `docs/publishing.md` already says. This changes none of that.
- **The first deploy needs a Settings change** (Pages → deploy from `gh-pages`), made
  after the branch exists.
- **The script is tested against a sandbox clone with a local bare remote, not the real
  one.** Its first run against GitHub is the first time the push, the lease and Pages are
  seen together, and that happens on the laptop.
