# CLAUDE.md — Market's Agentic Predictor (M.A.P.)

> Save this file at the repo root (`~/Desktop/M.A.P./CLAUDE.md`). Claude Code reads it every session.

---

## 1. What this project is

M.A.P. turns unstructured financial news into **calibrated, falsifiable probabilistic price forecasts**, using local open-weight models only. Three specialised agents run in sequence; the output is a schema-validated JSON forecast that feeds a Monte Carlo simulation and a fan chart.

The project is judged on **methodological rigour, not feature count.** Every claim it makes must be measurable, reproducible, and compared against a stated baseline. **A forecast that cannot be scored is a bug, not a feature.**

---

## 2. Working agreement — this is a learning project

1. **Explain before you write.** Before creating any non-trivial module, state in ≤150 words: the problem it solves, one or two alternatives considered, and why you rejected them. Then write the code.
2. **One module at a time.** Finish it, test it, and stop for approval before moving on. Do not generate the whole repo in a single pass.
3. **Write an ADR** in `docs/decisions/NNNN-short-title.md` for every non-obvious choice. Format: *Context / Options / Decision / Consequences*.
4. **Never add a dependency silently.** Name it, justify it, and add it to `pyproject.toml` in the same change.
5. **Push back.** If a request is a bad idea, say so *before* implementing it. Agreeableness is not helpfulness.

---

## 3. Hard constraints

- **Hardware: Apple M1 (2021), 16 GB unified memory.** Models load **one at a time**. Never assume two are resident simultaneously.
- **Inference is local only.** Never call a hosted LLM API. Never introduce an LLM API key.
- **Backend is OpenAI-compatible HTTP.** Default: LM Studio at `http://localhost:1234/v1`. Ollama at `http://localhost:11434/v1` must work by changing config alone.
- **The strings "LM Studio" and "Ollama" must not appear in application code** — only in config files, docs, and tests. If they leak into a module, the abstraction is broken and must be fixed.

---

## 4. Architecture rules

- **An agent is a contract, not a model.** It is `(input type) -> (output type)`. Swapping the model behind an agent is a config edit, never a code edit. If you find yourself editing `agents/*.py` because a new model was released, the abstraction leaked.
- **Prompts live in `prompts/` as versioned markdown files** (`scenario_analyst.v1.md`), never as string literals in Python. Prompts are not portable across models; versioning lets you hold per-model variants without touching logic.
- **Every LLM call goes through `providers/`.** No other module may make an HTTP call to a model.
- **Every market-data call goes through `data/providers/`.** Same rule, same reason.

---

## 5. Model registry (Phase 1)

| Agent | Role | Model | Approx. RAM |
|---|---|---|---|
| 1 — Intake | Compress raw news into dense material facts | Llama 3.2 3B Instruct | ~2.0 GB |
| 2 — Analyst | Three-scenario macro/micro reasoning | Gemma 4 12B IT (Q4_K_M) | ~7.6 GB |
| 3 — Structuralist | Narrative → schema-valid JSON | Qwen3 4B | ~2.5 GB |

**Agent 3 is deliberately small.** With JSON-schema constrained decoding the sampler makes invalid tokens unreachable, so model intelligence is not the binding constraint on output validity. Paying 5 GB for an 8B there would be waste on 16 GB of RAM.

**Read model IDs from `GET /v1/models` at startup — never hardcode them.** LM Studio and Ollama name identical weights differently. Fail fast with a clear, actionable error if a configured model is not loaded.

---

## 6. Non-negotiables

- **Disk cache on every LLM call**, keyed by `sha256(model_id + prompt + sampling_params)`. On this hardware a 12B runs at roughly 8–15 tok/s; without a cache, backtesting is not merely slow, it is impossible. This is load-bearing infrastructure, not an optimisation.
- **Determinism where available.** `temperature=0` for Agents 1 and 3. Record seed, model ID, model digest, and all sampling parameters in every run manifest.
- **Full trace.** Every run writes `runs/<run_id>/trace.jsonl` containing every prompt and every raw response. This is the audit trail *and* the input to the Phase 2 evaluation harness.
- **The test suite must pass with the inference server switched off.** Use a `FakeProvider` that replays recorded fixtures. If `pytest` requires a live model, CI is broken and the repo looks unfinished.
- **No network calls in unit tests. Ever.**

---

## 7. Code standards

- Python 3.12; `uv` for environment and dependency management; `pyproject.toml` (no bare `requirements.txt`)
- `pydantic` v2 — all schemas and config. `typer` — CLI. `httpx` — HTTP. `structlog` — logging.
- `ruff` (lint + format), `mypy --strict`, `pytest` with `pytest-cov`
- Type hints everywhere. No bare `except:`. No `print()` in library code — use the logger.
- Docstrings explain **why**, not **what**. The code already says what.

---

## 8. Phase discipline

**Phase 1 (current).** Provider layer, three agents, schema + validators, cache, market data + ticker search, CLI, tests. Ends when `map run AAPL` produces a validated forecast JSON and a chart, end to end — even a bad forecast.

- **Phase 2.** Monte Carlo engine, evaluation harness, baselines (random walk, GARCH), scoring rules (CRPS, Brier, log score).
- **Phase 3.** Probability calibration (isotonic regression), self-consistency ensembling, architecture ablation study.
- **Phase 4.** UI (Streamlit), packaging, publication.

**Do not write Phase 2+ code during Phase 1.** If a Phase 1 decision would block a later phase, raise it — do not silently build ahead.

---

## 9. Known traps — do not let these slip

- **Training-cutoff leakage.** The models already know what happened to well-known tickers historically. Any backtest on pre-cutoff news is contaminated and any good result from it is meaningless. Design for this from day one and document it prominently in the README.
- **Prompt injection.** RSS and news text are untrusted input flowing into a model that emits numbers. Delimit and quarantine feed text; never let it be read as instructions.
- **Model tags are mutable.** A registry can silently re-point `gemma4:12b` to different weights, invalidating every cached result. Pin by digest in run manifests, not by tag.
- **Overclaiming.** Inference is local; **price and news data are not.** The README must say "all inference is local, no data is sent to a third-party model provider" — never "100% offline."

---

## 10. Out of scope

No trading, no order execution, no broker integration, no position sizing, no financial advice. The README carries an explicit disclaimer stating the project is a research and engineering exercise.
