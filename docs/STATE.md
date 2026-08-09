# STATE.md — where the project actually is

> Save at `~/Desktop/M.A.P./docs/STATE.md`.
>
> **This file is the handoff between chat sessions.** A fresh Claude Code session reads
> `CLAUDE.md` for the rules and this file for the situation. Keep it current or it
> becomes actively harmful — a stale STATE.md is worse than none, because it will be
> trusted.
>
> **Rule: this file is updated at the end of every session, before the chat is closed.**

---

## Current phase

**Phase 1** — provider layer, three agents, schema, cache, market data, CLI, tests.

Nothing from Phase 2+ gets built until every criterion below passes.

### Phase 1 definition of done

1. `map health` verifies the local server, lists available models, and reports which
   configured models are missing.
2. `map search "apple"` returns `AAPL` from the local SQLite symbol table.
3. `map run AAPL --horizon 21` executes all three agents and writes
   `runs/<run_id>/forecast.json`, validated against the schema.
4. The same run writes `runs/<run_id>/trace.jsonl` (every prompt and raw response) and
   `manifest.json` (model digests, seeds, sampling params, data provider used).
5. A second identical run completes in under 2 seconds with **zero** calls to the
   inference server — cache hit.
6. `pytest` passes with the inference server **switched off**, using `FakeProvider` and
   recorded fixtures. *(This is the one that makes CI possible. Do not compromise on it.)*
7. `ruff check` and `mypy --strict` are clean.
8. `runs/<run_id>/chart.html` shows historical price plus three labelled scenario paths.

Criterion 7 (`ruff check` and `mypy --strict` clean) passes today over the code that
exists. The other seven: **not started** — they need modules 2–7.

---

## Status

**Done**

- `CLAUDE.md` written (working agreement, constraints, architecture rules, model registry)
- Phase 1 kickoff brief written with acceptance criteria
- Architecture designed and approved: layout, module contracts, dependency direction,
  `map run` data flow
- ADRs 0001–0005 written
- Repo skeleton on disk: `pyproject.toml`, `.gitignore`, `README.md`,
  `config/default.toml`, package tree under `src/mapf/`
- Toolchain live: `uv` (Homebrew), Python 3.12.13, all dependencies synced
- **Under version control.** `git init` + initial commit, 44 files. Local only.
- **Module 1 — `mapf.core` built and green.** `models.py`, `ports.py`, `errors.py`,
  `hashing.py`, `schema.py`
- **Module 2 — `mapf.settings` built and green.** `loader.py` (TOML + env overlay),
  `registry.py` (agent -> alias -> `ModelSpec`), `__init__.py` re-exporting the
  public names
- 160 unit tests; 100% line coverage of `core` and `settings`; `ruff check`,
  `ruff format --check`, `mypy --strict` and `lint-imports` (4/4) all clean, with
  no inference server and no network

**In progress**

- Nothing. Awaiting approval of module 2 before module 3.

**Next action**

- Build **one module at a time**, stopping for approval after each, per `CLAUDE.md` §2.2:
  1. ~~`mapf.core` — models, ports, errors, hashing~~ **done**
  2. ~~`mapf.settings` — TOML + env loading, model registry, placeholder rejection~~
     **done** — resolved as `loader.py` + `registry.py` with `__init__.py` re-exports
  3. `mapf.providers` — `openai_compat`, `caching`, `fake`
  4. `mapf.prompts` — loader plus the three v1 templates
  5. `mapf.agents` — intake, analyst, structuralist with the repair loop
  6. `mapf.data` — symbols, providers + chain, parquet cache, news
  7. `mapf.pipeline`, `mapf.render`, `mapf.bootstrap`, `mapf.cli`

- `README.md` is written and carries the four required honest-claims sections per
  `CLAUDE.md` §9–10: training-cutoff leakage; "all inference is local, no data is sent
  to a third-party model provider" (never "100% offline"); name search is **US-listed
  only**; "deterministic where the backend honours it", not "reproducible". Plus the
  no-financial-advice disclaimer and the ten-row dependency table.

---

## Environment

| Thing | Value |
|---|---|
| Machine | Apple M1 (2021), 16 GB unified memory |
| Inference backend | LM Studio, `http://localhost:1234/v1` |
| Models pulled | *(none yet — record exact IDs from `GET /v1/models` once pulled)* |
| Python | 3.12.13 via `uv` (uv installed with Homebrew) |
| Repo | `~/Desktop/M.A.P.` — local only, not yet on GitHub |
| Import package | `mapf` · CLI script name `map` |

---

## Open questions

Things not yet decided. Move each to an ADR once resolved, and delete it from here.

1. Agent 1's compression target — fixed token budget, or ratio of input length?
2. Where the news corpus lives for reproducible runs — in-repo fixtures, or a gitignored
   local directory with hashes recorded in the manifest? *(Leaning: gitignored `news/`,
   which is what `.gitignore` currently assumes, with `source_doc_ids` in the manifest
   carrying provenance. Not yet decided — third-party news text is not ours to commit,
   but a gitignored corpus makes a run unreproducible by anyone else.)*
3. ~~Whether the cache key should include the prompt *file version* as well as the prompt
   text~~ — **answered by ADR 0001.** The rendered prompt text is already in the key, so a
   prompt edit invalidates automatically; adding the version would be redundant for
   invalidation. The prompt file name, version and content hash are still recorded in the
   **manifest**, because provenance and invalidation are different jobs.
4. Does the target backend expose a weight digest on `GET /v1/models`? If not, ADR 0001
   degrades to tag-only pinning and `map health` must say so out loud. Resolve at the
   first `map health` run.
5. Does the backend honour `seed`? Recorded as *requested* either way.
6. Which reference ticker and corporate-action-free window to pin for the ADR 0003
   cross-provider agreement test.
7. ~~Docstrings leak into the decode grammar.~~ **Resolved 2026-08-09.** `description`
   and `title` are stripped by `mapf.core.schema.decode_schema`; docstrings serve
   developers, the grammar serves the model, and conflating them would mean a docstring
   edit silently changes model behaviour. Field-level hints, if ever wanted, go in
   `json_schema_extra` — curated, versioned with the prompt, governed as prompt content
   under `CLAUDE.md` §4. `tests/unit/test_decode_schema.py` is the enforcement.
8. **Does the backend's grammar engine resolve `$ref`?** `Scenario` appears three times,
   so pydantic emits `$defs` + `$ref` rather than inlining. Most engines handle it; some
   do not. If it chokes, flatten the schema. Resolve at first contact with the backend.
9. ~~Whether to cut `pandas-datareader` and `rapidfuzz`.~~ **Resolved 2026-08-09 — both
   cut.** Stooq is ~15 lines of `httpx.get` + `pd.read_csv`; SQLite FTS5 covers search.
   Runtime dependencies: 12 -> 10.
10. **Is enforcing `temperature == 0` for intake and structuralist too strict?** Added in
   module 2 as `DeterminismPolicyError`, on the strength of `CLAUDE.md` §6 calling it a
   non-negotiable — but it was not requested, and Phase 3 self-consistency ensembling may
   want sampling on Agent 3. Easy to remove: one validator in
   `mapf/settings/loader.py`. Confirm or veto.

---

## Known issues

1. **A parent-directory `CLAUDE.md` is intentional, not a problem.**
   `~/Desktop/CLAUDE.md` loads into every session in this repo because `~/Desktop` is a
   parent of it. That is deliberate: it is Kamil's global context for GitHub builds, and
   it is meant to load here. Do not "fix" it, and do not propose
   moving this repo to escape it.
2. **Moving the repo drops dotfiles.** `.gitignore` was lost in the
   `Desktop → Projects → Desktop` round trip on 2026-08-09 and had to be rewritten.
   Now mitigated by version control, but check after any future move.
3. ~~The vendor-string ban is unenforced.~~ **Closed 2026-08-09** —
   `test_no_vendor_names_appear_in_application_code` scans every `.py` under `src/`.
4. ~~Not under version control.~~ **Closed 2026-08-09** — `git init` + initial commit.
   Local only, not on GitHub.

---

## Decision log

ADRs live in `docs/decisions/`. Index them here as they are written.

| # | Title | Status |
|---|---|---|
| [0001](decisions/0001-cache-key-composition.md) | Cache key composition | Accepted |
| [0002](decisions/0002-constrained-decode-surface.md) | Narrow the constrained-decode surface | Accepted |
| [0003](decisions/0003-price-adjustment-semantics.md) | Price adjustment semantics across providers | Accepted |
| [0004](decisions/0004-import-boundary-enforcement.md) | Enforce import boundaries in CI | Accepted |
| [0005](decisions/0005-untrusted-text-and-document-identity.md) | Untrusted text as a type, document identity over raw bytes | Accepted |
| [0006](decisions/0006-justification-before-figures.md) | `justification` is emitted before the figures | Accepted |

### Pinned in review, ADR owed

Binding decisions with no ADR yet. Write them as 0006–0007 when the module lands.

- **Network-dependent tests** are marked `@pytest.mark.network` and deselected by default
  via `addopts`. Opt in with `pytest -m network`. This is what reconciles the ADR 0003
  cross-provider test with DoD criterion 6.
- **SEC EDGAR access** requires a descriptive `User-Agent` (name + contact email);
  without it EDGAR returns 403 and blocks the IP for ~10 minutes. It lives in
  `config/default.toml`, never in code, and startup validation rejects the shipped
  placeholder. Requests throttled below EDGAR's 10/s ceiling.
- **Prompts are package data** at `src/mapf/prompts/*.md`, loaded via
  `importlib.resources`, so they survive being installed as a wheel.

---

## Session log

Newest first. One or two lines each — what changed, what broke, what's next. If an entry
needs a paragraph, it needed an ADR instead.

- **2026-08-09 (4)** — `git init` + initial commit (44 files); a `.gitignore` bug found
  while staging — bare `news/` is unanchored and was swallowing `tests/fixtures/news/`,
  now `/news/`. Module 2 `mapf.settings` built: `loader.py`, `registry.py`,
  `__init__.py` re-exports. ADR 0006 (justification before figures) written; ADR 0001's
  `PlaceholderConfigError` gained a `hint`. `decode_schema()` added to `core` with a
  test asserting no `description`/`title` at any depth. Adversarial float tests found
  the tolerance boundary is **asymmetric** — a nominal 1e-6 is accepted above 1.0 and
  rejected below — now pinned. `pandas-datareader` and `rapidfuzz` dropped (12 -> 10
  deps). Vendor-string ban now enforced by test. 160 tests, 100% coverage of `core` and
  `settings`. Known issue 1 (loose Desktop `CLAUDE.md`) verified still open.
- **2026-08-09 (3)** — Module 1 `mapf.core` built: `models.py`, `ports.py`, `errors.py`,
  `hashing.py`. 112 tests, 100% coverage of `core`, ruff + `mypy --strict` +
  `lint-imports` clean. ADR 0005 written; ADR 0001 amended with the defensive
  digest → composite → tag fingerprint ladder. Toolchain installed (`uv` via Homebrew,
  Python 3.12.13). `README.md` written with the four honest-claims sections.
  `import-linter` caught a missing `mapf.bootstrap` module — created as a docstring-only
  stub. Repo moved back to `~/Desktop/M.A.P.`; `.gitignore` was lost in the round trip
  and rewritten. **Dependency review:** `pandas-datareader` and `rapidfuzz` are both
  arguably cuttable — see open question 9. Awaiting approval before module 2.
- **2026-08-09 (2)** — Architecture approved with five amendments (forbidden import
  contracts; `config`→`settings` package rename; `@pytest.mark.network`; raw-hash +
  `UntrustedText` split; SEC User-Agent). ADRs 0001–0004 and the repo skeleton written.
  Repo moved `~/Desktop/M.A.P.` → `~/Projects/M.A.P.` mid-session; `CLAUDE.md` landed in
  `docs/` and needs moving back to the root. No implementation code yet.
- **2026-08-09** — Project scoped. Architecture corrected (Qwen3 4B not 7B, horizon added
  to schema, `annualised_vol` replaces `implied_volatility_shift`). `CLAUDE.md` and Phase 1
  brief written. No code yet.

---

## Session rituals

**Ending a session** — paste this before you close the chat:

> Update `docs/STATE.md`: move completed items to Done, set the Next action, add any new
> open questions or known issues, and append a one-line session log entry. Write ADRs for
> any non-obvious decision we made today. Do not summarise the conversation — record only
> what a fresh session needs in order to continue.

**Starting a session** — paste this first:

> Read `CLAUDE.md` and `docs/STATE.md`. Tell me in five lines where the project is and what
> the next action is. Do not start work until I confirm.
