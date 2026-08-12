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

**All eight pass**, as `tests/integration/test_definition_of_done.py` — one test per
criterion, named for it, against `FakeProvider` with no server and no network.
Criterion 5 is asserted on transport-call count rather than a stopwatch: a clock
measures the machine, the counter measures the claim.

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
- **Module 3 — `mapf.providers` built and green.** `openai_compat.py` (the only
  module that speaks HTTP to a model), `caching.py` (disk cache as an `LLMProvider`
  decorator), `fake.py` (fixture replay, ships in `src/`), `keys.py` (one shared
  request-key derivation)
- **Module 4 — `mapf.prompts` built and green.** `sanitise.py` (delimiter
  neutralisation), `loader.py` (`FilePromptStore`), and the three v1 templates as
  package data
- **Module 5 — `mapf.agents` built and green.** `base.py` (contract + shared
  plumbing), `intake.py`, `analyst.py`, `structuralist.py` with the repair loop,
  plus `structuralist_repair.v1.md`
- **Module 6 — `mapf.data` built and green.** `symbols.py` (SEC -> SQLite FTS5,
  explicit sync), `news.py` (local dir + RSS, raw-byte ids), `cache.py`
  (vintage-keyed parquet), `providers/{frames,yfinance_provider,stooq,chain}.py`
- 409 unit tests + 2 network-marked contract tests; 100% line coverage of all six
  built modules; `ruff check`, `ruff format --check`, `mypy --strict` and
  `lint-imports` (4/4) all clean, with no inference server and no network
- **Module 7 — `mapf.pipeline`, `mapf.render`, `mapf.bootstrap`, `mapf.cli` built and
  green.** `run.py` (ordering + artifact assembly), `manifest.py` (the Phase 2
  handshake), `trace.py` (`JsonlTrace` + `CountingTrace`), `chart.py` (three paths,
  no volatility band), the composition root, and `map health|search|run|symbols sync`
- **474 tests, 100% line coverage of every module**, `ruff`, `mypy --strict` and
  `lint-imports` (4/4) clean
- Deprecation warnings are errors **scoped to `mapf.*`** (ADR 0010) — it caught a
  deprecated `importlib.abc.Traversable` on its first run

**In progress**

- Nothing. **Phase 1 code is complete.** First live `map health` done 2026-08-11: server
  reachable, 4 models listed, weight pinning degraded to `tag`, two aliases missing (now
  fixed in config). The grammar probe has **not yet run** — it needs the structuralist
  model resolved, so it was skipped. Re-run `map health` to reach it.

**Next action**

- Build **one module at a time**, stopping for approval after each, per `CLAUDE.md` §2.2:
  1. ~~`mapf.core` — models, ports, errors, hashing~~ **done**
  2. ~~`mapf.settings` — TOML + env loading, model registry, placeholder rejection~~
     **done** — resolved as `loader.py` + `registry.py` with `__init__.py` re-exports
  3. ~~`mapf.providers` — `openai_compat`, `caching`, `fake`~~ **done**
  4. ~~`mapf.prompts` — loader plus the three v1 templates~~ **done**
  5. ~~`mapf.agents` — intake, analyst, structuralist with the repair loop~~ **done**
  6. ~~`mapf.data` — symbols, providers + chain, parquet cache, news~~ **done**
  7. ~~`mapf.pipeline`, `mapf.render`, `mapf.bootstrap`, `mapf.cli`~~ **done**

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
| Models pulled | intake `llama-3.2-3b-instruct` · analyst `google/gemma-4-12b-qat` · structuralist `qwen/qwen3-4b-2507` (verified 2026-08-11) |
| Weight pinning | **unavailable** — `/v1/models` exposes no digest; `fingerprint_source: "tag"` (ADR 0001) |
| Structuralist build | **MLX**, quant reported as `4bit`. Suspect this first if the grammar probe returns `accepted_not_enforced` |
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
4. ~~Does the target backend expose a weight digest on `GET /v1/models`?~~ **Answered
   2026-08-11 — no.** The response carries exactly `id`, `object` and `owned_by`, and the
   last two are constant across every model, so the composite rung has nothing to build
   from and pinning degrades to `tag`. Recorded as an observed fact in ADR 0001, together
   with the trade we declined: the backend's *native* endpoint does expose arch, params
   and quantisation, and calling it would make the code backend-aware
   (`CLAUDE.md` §3). Not to be re-litigated.
5. Does the backend honour `seed`? Recorded as *requested* either way.
6. ~~Which reference ticker and corporate-action-free window to pin for the ADR 0003
   cross-provider agreement test.~~ **Resolved 2026-08-11 — MSFT, 2024-02-05 to
   2024-02-09.** `tests/contract/test_provider_agreement.py`, network-marked.
7. ~~Docstrings leak into the decode grammar.~~ **Resolved 2026-08-09.** `description`
   and `title` are stripped by `mapf.core.schema.decode_schema`; docstrings serve
   developers, the grammar serves the model, and conflating them would mean a docstring
   edit silently changes model behaviour. Field-level hints, if ever wanted, go in
   `json_schema_extra` — curated, versioned with the prompt, governed as prompt content
   under `CLAUDE.md` §4. `tests/unit/test_decode_schema.py` is the enforcement.
8. **Does the backend's grammar engine resolve `$ref`?** *(now probed, not guessed —
   `map health` sends one minimal constrained request against the real
   `decode_schema(ScenarioSet)` and reports `enforced` / `accepted_not_enforced` /
   `rejected` / `inconclusive`, naming the flattening fix if rejected. Skip with
   `--no-grammar-probe`.)* `Scenario` appears three times,
   so pydantic emits `$defs` + `$ref` rather than inlining. Most engines handle it; some
   do not. If it chokes, flatten the schema. Resolve at first contact with the backend.

   **Still open** — the 2026-08-11 health run never reached the probe, because it needs
   the structuralist model resolved and the alias did not match. Re-run after the config
   fix.

   **Suspect the runtime before the schema.** The verified Qwen build is **MLX**, not
   GGUF (the server reports its quant as `4bit` rather than `Q4_K_M`). MLX runtimes have
   weaker constrained-decoding support than llama.cpp/GGUF. So if the probe returns
   `accepted_not_enforced` — request accepted, output not constrained — the first thing
   to try is **the GGUF build of the same model**, not a change to
   `mapf.core.schema.decode_schema`. A `rejected` outcome points at the schema; an
   `accepted_not_enforced` outcome points at the runtime.
9. ~~Whether to cut `pandas-datareader` and `rapidfuzz`.~~ **Resolved 2026-08-09 — both
   cut.** Stooq is ~15 lines of `httpx.get` + `pd.read_csv`; SQLite FTS5 covers search.
   Runtime dependencies: 12 -> 10.
10. ~~Is enforcing `temperature == 0` too strict?~~ **Resolved 2026-08-09 — confirmed with
   an auditable override.** See ADR 0007. Phase 2's evaluation harness must read
   `models.allow_nondeterministic` from the manifest and exclude or separate those runs.
11. ~~Recording real fixtures.~~ **Resolved 2026-08-10 — a flag with a mandatory explicit
   destination: `map run --record-to <dir>`.** A flag rather than a separate script,
   because fixtures must come from the exact code path used in production or they are not
   fixtures. The destination is mandatory and has no default, because a production command
   must never silently overwrite `tests/fixtures/`; copying recordings into the test corpus
   stays a deliberate human act. **Recordings contain news text and must be reviewed before
   being committed** — third-party text is not automatically ours to redistribute, and a
   recording made from a private feed may not be shareable at all. Implement with the CLI
   (module 7).
12. **Inter-token stall timeout (streaming) — Phase 4, do not build now.** `read_timeout_s`
   is a 600 s ceiling on the *whole* response, so a genuinely hung server blocks for ten
   minutes before failing. Streaming the response would allow a much shorter stall timeout
   measured between tokens: fail in seconds when nothing is arriving, while still permitting
   a long total generation. It also gives progress feedback, which the Phase 4 UI will want
   regardless. Deferred because streaming changes the provider contract and the cache
   would need to buffer a full response before storing it.

---

### What the knowledge graph revealed

Run `/graphify` at phase boundaries only — a full build costs ~130k tokens; use
`--update` in between.

The 2026-08-11 build independently confirmed all four import contracts from AST
rather than from the `import-linter` config: `core` has no outgoing first-party
edge, `agents` reaches none of providers/data/settings, and there is no cycle at
package or module-file level. The package graph is a clean star into `core`.

**The sharpest finding was about this file.** The only two AMBIGUOUS edges in the
whole graph both hang off the open-questions register below, linking it to
`Agent 3 returns ScenarioSet only` (ADR 0002) and to the materiality test in the
intake prompt. The extractor could not classify them because they are not
citations — they are *unresolved decisions pointing at live code*. That is worth
stating plainly: **the open questions in this file are structure, not
documentation.** Each one is an edge into something already built, and closing one
is a change to the system rather than a note about it. Treat this section with the
same care as an ADR, not as a scratchpad.

Two node-level findings, both measured rather than assumed: `PriceWindow` (in 40 /
out 4) and `ModelInfo` (in 50 / out 5, and 4 of those 5 are AST false edges from
module-level import attribution) are shared vocabulary, not god objects — the high
betweenness is many communities agreeing on one word, which is what the layering
was for.

### First successful v2 run — 2026-08-12

`map run AAPL --horizon 21`, run `41bc6867`. Spot 304.91.

| | bullish | base | bearish |
|---|---|---|---|
| weight | 0.30 | 0.50 | 0.20 |
| return | +0.03 | +0.01 | -0.03 |
| vol | 0.20 | 0.18 | 0.22 |

- **Transcription fidelity 1.0.** All three ESTIMATE lines parsed, zero divergent.
  v2's premise — analyst states magnitudes, structuralist transcribes — is now
  measured rather than claimed.
- **Degenerate spread: no.** 0.06 against a floor of 0.0229.
- **Justification lengths 234 / 209 / 191, zero at ceiling.** The copying stopped,
  and the text reads as the model's own compression rather than the analyst's
  paragraph. See the ceiling note below.
- One false positive on the numeral check (`21`, from "a 21-day horizon") — fixed
  by grounding the horizon and spot price, which the model legitimately knows.
- Vols 0.18–0.22, against AAPL's realised ~0.25. Much closer than v1's 0.05, still
  a Phase 3 calibration question.

**Getting there required a real fix.** The first v2 attempt failed with "analyst
output rejected... likely a refusal; length was 0 characters". It was not a
refusal: this build of the analyst reasons into a separate `reasoning_content`
field before answering, and it spent the entire default budget thinking. Measured
at a fixed 1500-token budget with identical facts, v1 reasons 1114 tokens then
answers; v2 reasons 1497 — all of it — and never answers. `max_tokens` is now
explicit at 12000, budget exhaustion raises its own typed error naming the token
counts, and `reasoning_tokens` is recorded. **Note the analyst runs at
temperature 0.7, so reasoning length varies run to run** — 12000 is headroom, not
a guarantee.

**Proposed: raise the justification ceiling back to 400.** The 240 cap was set on
reasoning that ADR 0014 records as unsupported. This run confirms the mechanism was
the instruction, not the room: with "the justification is yours, not the analyst's"
in place, the model composes rather than copies. But the longest justification came
in at 234 of 240 — 98% of the cap — so 240 is now constraining real synthesis
rather than preventing copying. `justifications_at_ceiling` is the regression
signal to watch if it is raised.

### Logged for Phase 3 — do not fix now

**Volatility is badly calibrated.** The first live run gave the base case an
`annualised_vol` of 0.05 for AAPL, whose realised volatility is nearer 0.25 — off
by a factor of five. That is a calibration problem, not a units one, and it is
exactly what Phase 3's isotonic regression exists to address. Do not attempt to fix
it by editing prompts until there is a scoring harness to measure the fix against.

### Logged for Phase 2 — do not build now

**Rendering must become opt-in.** `write_chart` inlines the whole plotly bundle, so
every run directory costs about **4.5 MB of identical JavaScript**. A backtest over a
few hundred news items would write gigabytes of it. Charts are for humans and a
backtest has no human reading each one, so Phase 2 should make rendering a flag on
`execute` rather than something it always does. Measured, not estimated: sharing one
run across the read-only DoD assertions took that test file from **151 s to 0.7 s**,
and the difference was almost entirely chart writing.

**A single-agent variant is not yet a config change.** Verified rather than assumed,
and the answer is no — see Known issues 4 below. Do not build the variant until
Phase 2 can score it; building a comparison before there is anything to measure it
with is the wrong order. But the blocker below is worth removing sooner than that,
because it also blocks per-model prompt variants, which is a Phase 1/2 activity.

### First live run — 2026-08-11, and what it changed

`map run AAPL --horizon 21` completed end to end. **The machine worked and the
numbers did not**, and the diagnosis is worth keeping because the first hypothesis
was wrong in an instructive way.

Reported output was `+0.1% / +0.0% / -0.1%`. Three separate defects, and only the
last is the one it looked like:

1. **A display bug caused a wrong diagnosis.** The CLI formatted with `:+.1f`, so a
   stored `0.05` printed as `+0.1` — a doubling. The terminal and the artifact
   disagreed, and the disagreement is what the diagnosis started from. Fixed first
   and separately.
2. **The analyst was never asked for magnitudes.** `scenario_analyst.v1` line 25
   requested "a **qualitative** statement of where the price could go", and the
   model complied: "moderate upward move", "relatively flat", "sharp downward
   move". Not one numeral. Meanwhile `structuralist.v1` said "you **transcribe what
   is already there**" and "convert faithfully and **conservatively rather than
   inventing precision**". Agent 2 was told not to produce numbers and Agent 3 was
   told not to invent them — **someone has to**, and Agent 3 resolved the
   contradiction by being maximally conservative. That is a design contradiction in
   the prompts, not a model failure.
3. **Two adjacent numeric fields on different conventions.** `annualised_vol` is a
   fraction, `price_modifier_pct` was percentage points, and the field names taught
   the inconsistency — one carried a unit suffix, the other did not. The output is
   coherent as fractions (`+5% / flat / -10%`) and meaningless as percentage
   points. The schema `description`s that might have said so are stripped before
   the model sees them (ADR 0002), and neither prompt picked up the slack.

Fixed in v2: fractions throughout, `price_modifier_pct` → `price_return`,
`schema_version` → `2.0.0`, the analyst states `Return:` and `Vol:` as decimals
with a worked example, the structuralist copies rather than converts.

**The diagnostic experiment ran on 2026-08-12 — see ADR 0014.** Units was entirely
binding, the conservatism clause entirely inert, and the control reproduced production
exactly, which is what makes the table evidence rather than anecdote. Both original
hypotheses were wrong in opposite directions.

*(superseded note)* ~~The diagnostic experiment has NOT been run~~ — the server was down when it was
attempted. `scratchpad/probe/variants.py` pins the v1 prompt text inline so it
remains valid; it runs four Agent-3-only variants (control, units stated,
conservatism removed, both) against the cached narrative to establish which
instruction was binding. It is diagnostic only: **a good result from "conservatism
removed" is not a licence to let a 4B invent magnitudes from prose** — that is the
same surface that fabricated 66.3%.

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
5. ~~**Prompt selection is hardcoded in `agents/`.**~~ **Closed 2026-08-12.** `template`
   and `version` are constructor parameters with class-level defaults, the version is
   read from a `[prompts]` config table, and `bootstrap` passes it through. A per-model
   prompt variant is now a config edit, which is what `CLAUDE.md` §4 always claimed.
   The pipeline half stands and is fine: `execute` still hardcodes the three-stage
   sequence, and a different topology is honestly a different pipeline function.

   *Original text:* **Prompt selection is hardcoded in `agents/`, and that is an abstraction leak.**
   Each agent module holds `TEMPLATE` and `VERSION` as module constants
   (`TEMPLATE = "structuralist"`); no agent takes a template as a constructor
   parameter. Two consequences, and the second matters sooner than the first:
   - A single-agent ablation variant would require editing `agents/*.py`, not just
     config. (`pipeline.run.execute` also hardcodes the three-stage sequence and
     `Agents` has exactly three slots — that half is fine and expected: a different
     topology is honestly a different pipeline function.)
   - **A per-model prompt variant is also a code edit today.** `CLAUDE.md` §4 says
     prompts are versioned precisely so per-model variants can coexist "without
     touching logic" — and right now they cannot. Tuning `structuralist.v2` for
     whichever model actually ships means editing an agent.

   Fix, and it is small: make `template` and `version` constructor parameters on
   `LLMAgent` with the current values as defaults. Three agent signatures and
   `bootstrap.build_run`. Worth doing before prompt tuning starts.

---

## Decision log

ADRs live in `docs/decisions/`. Index them here as they are written.

| # | Title | Status |
|---|---|---|
| [0001](decisions/0001-cache-key-composition.md) | Cache key composition | Accepted (amended 2026-08-10: decode schema is in the key) |
| [0002](decisions/0002-constrained-decode-surface.md) | Narrow the constrained-decode surface | Accepted |
| [0003](decisions/0003-price-adjustment-semantics.md) | Price adjustment semantics across providers | Accepted (amended 2026-08-11: basis is `split_adjusted`) |
| [0004](decisions/0004-import-boundary-enforcement.md) | Enforce import boundaries in CI | Accepted |
| [0005](decisions/0005-untrusted-text-and-document-identity.md) | Untrusted text as a type, document identity over raw bytes | Accepted (amended 2026-08-10: `QuarantinedText`) |
| [0006](decisions/0006-justification-before-figures.md) | `justification` is emitted before the figures | Accepted |
| [0007](decisions/0007-determinism-guard-with-auditable-override.md) | Determinism guard with an auditable override | Accepted |
| [0008](decisions/0008-inference-timeouts-and-failure-taxonomy.md) | Inference timeouts and the failure taxonomy | Accepted (amended 2026-08-10) |
| [0009](decisions/0009-deterministic-quarantine-delimiters.md) | Deterministic quarantine delimiters | Accepted |
| [0010](decisions/0010-scoped-deprecation-errors.md) | Deprecation warnings are errors, scoped to our own code | Accepted |
| [0011](decisions/0011-agent-contracts-and-the-repair-loop.md) | Agent contracts, the repair loop, and what none of it guarantees | Accepted |
| [0012](decisions/0012-price-cache-and-retroactive-adjustment.md) | The price cache and retroactive adjustment | Accepted |
| [0013](decisions/0013-ex-dividend-windows.md) | Forecast price, score price, flag where they diverge | Accepted |
| [0014](decisions/0014-the-units-experiment.md) | Diagnosing the first live run by experiment | Accepted |

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

- **2026-08-11** — Module 6 `mapf.data` built. ADR 0012 written on the retroactive
  adjustment trap. **ADR 0003's canonical basis was unimplementable**: Stooq publishes
  no dividend adjustment, so the fallback would have raised on every call — a fallback
  that existed on paper only. Basis amended to `split_adjusted`, which both providers
  can produce, matches what `price_modifier_pct` forecasts, and drifts on splits rather
  than quarterly dividends. Price cache is keyed by vintage
  (`ticker/basis/fetched_on/range`) so two adjustment vintages can never be silently
  mixed. Chain now falls back on any `MarketDataError`. Symbol sync is an explicit
  command; search is offline and fails naming `map symbols sync`. **Phase 2 obligation
  recorded in ADR 0012: the evaluation harness must read `adjustment`, `provider` and
  `fetched_on` from the manifest and refuse to score across mixed values.**
  409 tests + 2 network-marked.
- **2026-08-10 (2)** — Module 5 `mapf.agents` built. ADRs 0010 and 0011 written.
  **ADR 0005 was not actually enforced**: `UntrustedText` is a `NewType` and could be
  constructed anywhere, so the type marked provenance but not sanitisation. Closed by
  splitting it — `UntrustedText` still marks provenance; a new `QuarantinedText` in
  `core.quarantine` carries the guarantee and has a module-private constructor token.
  `PromptStore.render` accepts only the latter, so the renderer cannot receive
  unsanitised text. Enforced by mypy, a runtime token check, and an AST test asserting
  one construction site. `Trace.record` now takes fields rather than a built event, so
  agents need no clock. 330 tests.
- **2026-08-10** — Module 4 `mapf.prompts` built: `sanitise.py`, `loader.py`, and the
  three v1 templates. ADR 0009 written. The central tension is resolved: a nonce
  delimiter would defeat DoD criterion 5, so delimiters are fixed and the payload is
  made unable to contain them — NFKC, then control/format stripping, then fixpoint
  marker deletion. Byte-identical rendering is asserted directly. ADR 0001 amended to
  carry the decode schema in the key; ADR 0008 amended with the standing rule that error
  enrichment must never re-enter the path that raised. Open questions 11 (`--record-to`)
  and 12 (streaming stall timeout, Phase 4) recorded. Deprecations are now pytest errors.
  291 tests, 100% coverage of all four built modules.
- **2026-08-09 (5)** — Module 3 `mapf.providers` built: `openai_compat`, `caching`,
  `fake`, `keys`. ADR 0008 written (timeouts and failure taxonomy). Its own tests found
  a recursion bug: a 404 on `/models` re-entered discovery through the error-enrichment
  path and never terminated — 404 is now translated to a missing model in `complete()`
  only. Determinism guard gained the `allow_nondeterministic` override and ADR 0007.
  Connect and read timeouts split (10 s / 600 s). Float-tolerance finding documented in
  the README. Known issue 1 closed: a parent `CLAUDE.md` is intentional. 224 tests, 100%
  coverage of `core`, `settings` and `providers`.
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
