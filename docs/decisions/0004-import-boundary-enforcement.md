# 0004 — Enforce import boundaries in CI

Status: Accepted · Date: 2026-08-09 · Phase 1

## Context

The architecture rests on a claim that cannot be verified by reading: `agents`
depends on the Protocols in `core` and never on the adapters in `providers` or
`data`. That claim is what makes DoD criterion 6 free — construct an agent with
`FakeProvider` and there is nothing to patch, because `httpx` is not reachable
from `agents` even transitively.

An architecture rule that lives only in `CLAUDE.md` degrades. One `from
mapf.providers import ...` added under time pressure is invisible in review and
silently converts the test suite into one that needs a live server.

A `layers` contract alone is insufficient, and this was the defect in the first
draft: `layers` permits *higher → lower*. `agents` (L3) importing `providers`
(L2) is a downward import, so it passes. The contract that must be enforced is
not "agents sits above providers" — it is "agents may not reach providers at
all."

## Options

1. **Convention plus code review.** Free, and fails on exactly the change that
   matters, because a boundary breach looks like an ordinary import.
2. **`layers` contract only.** Catches upward and cyclic imports. Misses every
   rule this design actually depends on.
3. **`layers` plus explicit `forbidden` contracts.**

## Decision

Adopt **`import-linter`**, configured in `pyproject.toml`, run in CI alongside
`ruff check` and `mypy --strict`. A boundary breach fails the build.

Four contracts:

- **`layers`** — the full stack, `cli → bootstrap → pipeline → agents → render →
  providers → data → prompts → settings → core`. This catches cycles and upward
  imports. The ordering among the L2 siblings (`render`, `providers`, `data`) is
  deliberately stricter than the true relationship, which is mutual
  independence; over-strictness costs nothing here.
- **`forbidden`: `mapf.agents` ↛ `mapf.providers`, `mapf.data`, `mapf.settings`.**
  Agents receive their dependencies; they never construct or configure them.
- **`forbidden`: `mapf.pipeline` ↛ `mapf.providers`, `mapf.data`.** The pipeline
  is parameterised by Protocols so it is testable end-to-end with fakes.
- **`forbidden`: `mapf.core` ↛ every other `mapf.*` module.** `core` is a sink.
  This is the contract that keeps the type layer importable from anywhere.

`mapf.bootstrap` is exempt by design — it is the composition root and the only
module permitted to know which concrete adapters exist.

## Consequences

- One dev dependency, and every new package must be placed in the layer list
  before it can be imported. That friction is the point: it forces the question
  "where does this belong?" at creation time rather than at refactor time.
- The vendor-string ban in `CLAUDE.md` §3 is *not* covered by this tool. A
  `ruff` rule or a dedicated test asserting the strings "LM Studio" and "Ollama"
  appear nowhere under `src/` is still required, and is tracked separately.
- `bootstrap`'s exemption is the one place where a boundary breach can still hide.
  It stays small and free of logic for that reason.
