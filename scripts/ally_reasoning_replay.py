"""Is ALLY's analyst runaway deterministic, or was it twice unlucky?

**Run this AFTER the clean band completes, never during.** It loads the 12B and
issues five analyst calls of up to 12,000 tokens each. Run concurrently with the
corpus it would contend for the same model, force KV swaps, and can push a real
item past the 1,300 s read timeout — turning a diagnostic into a failed item.

    uv run python scripts/ally_reasoning_replay.py

WHAT IT DECIDES

ALLY 2026-01-21 failed twice with `budget_exhausted`, both times at the 12,000-token
analyst ceiling, against a maximum of 9,094 across the 32 other completed items of
the band. It is now resolved by the repeat rule (ADR 0024) rather than by a blanket
reclassification. This replays the exact recorded prompt five times and reports the
reasoning-token distribution.

- **Five at the cap** — the runaway is a property of the document. Terminal was
  simply correct for this item, and a blanket flip of `budget_exhausted` would have
  reached the same answer here.
- **Some finishing well inside the budget** — the runaway is probabilistic. The
  repeat rule was the *better* answer than a blanket flip, because a blanket flip
  would also have discarded items that a retry would have rescued.

Either way it is a finding about the method, not only about ALLY, and it is recorded
in `Findings & Incidents` either way.

The prompt is read from the trace of the failed run rather than rebuilt, so this
replays what the model was actually asked. Nothing here writes to the ledger, the
cache, or the corpus.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

from mapf.bootstrap import build_llm_provider
from mapf.core.errors import ModelBudgetExhaustedError
from mapf.core.ports import Message, RenderedPrompt, SamplingParams
from mapf.settings import ModelRegistry, load

TICKER = "ALLY"
REPLAYS = 5


def _recorded_prompt(runs_dir: Path) -> RenderedPrompt | None:
    """The analyst prompt as it was actually sent, from any ALLY trace."""
    for trace in sorted(runs_dir.glob("*/trace.jsonl")):
        for line in trace.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            data = event.get("data") or {}
            if event.get("stage") != "analyst" or "messages" not in data:
                continue
            messages = tuple(
                Message(role=m["role"], content=m["content"]) for m in data["messages"]
            )
            if any(TICKER in m.content for m in messages):
                return RenderedPrompt(
                    template_name=str(data.get("template", "analyst")).rsplit(".", 1)[0],
                    template_version="replay",
                    template_sha256=str(data.get("template_sha256", "0" * 64)),
                    messages=messages,
                )
    return None


def main() -> int:
    settings = load()
    registry = ModelRegistry(settings.models)
    spec = registry.spec("analyst")
    # UNCACHED. A cached replay answers from its own first result and reports on a
    # server it never contacted, which is worse than not running the diagnostic.
    provider = build_llm_provider(settings, cached=False)
    model = registry.resolve("analyst", provider.list_models())

    prompt = _recorded_prompt(settings.paths.runs_dir)
    if prompt is None:
        print(f"no recorded analyst prompt for {TICKER} under {settings.paths.runs_dir}")
        return 1

    cap = spec.sampling.max_tokens or 0
    print(f"{TICKER}: {REPLAYS} replays of the recorded analyst prompt, cap {cap:,}")
    print(f"{'run':>4}  {'reasoning':>10}  {'visible':>8}  finish")
    lengths: list[int] = []
    for attempt in range(REPLAYS):
        # `attempt` varies so a cache placed in front of this later cannot collapse
        # five draws into one; sampling is otherwise exactly what the run used.
        try:
            response = provider.complete(
                model=model,
                prompt=prompt,
                sampling=SamplingParams(**spec.sampling.model_dump()),
                attempt=attempt,
            )
        except ModelBudgetExhaustedError as error:
            lengths.append(cap)
            print(f"{attempt + 1:>4}  {'AT CAP':>10}  {'—':>8}  budget_exhausted ({error})")
            continue
        reasoning = response.reasoning_tokens or 0
        lengths.append(reasoning)
        print(
            f"{attempt + 1:>4}  {reasoning:>10,}  {response.completion_tokens or 0:>8,}  "
            f"{response.finish_reason}"
        )

    at_cap = sum(1 for n in lengths if n >= cap)
    print()
    median = statistics.median(lengths)
    print(f"median {median:,.0f}   max {max(lengths):,}   at cap {at_cap}/{REPLAYS}")
    if at_cap == REPLAYS:
        print("DETERMINISTIC: terminal was simply correct for this item.")
    else:
        print(
            "PROBABILISTIC: the repeat rule was the better answer than a blanket "
            "flip, which would also have discarded items a retry would rescue."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
