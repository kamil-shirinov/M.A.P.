"""Is the analyst runaway a decoding loop, or genuinely long reasoning?

**Run this only when no band is executing.** It loads the 12B and issues analyst calls
of up to 12,000 tokens. Run beside a corpus it would contend for the same model, force
KV swaps, and can push a real item past the 1,300 s read timeout.

    uv run python scripts/analyst_runaway_replay.py

THE NATURAL EXPERIMENT: ACGL, NOT ALLY

Four items burned the analyst's whole budget. **Size is ruled out** (ADR 0027, addendum
2026-09-01): five of the six runaway documents have a same-company, same-template
sibling that is LARGER and terminated normally. So the question is content, and the
corpus contains one pair that isolates it almost perfectly:

    ACGL 2026-02-09   39,253 chars   FAILED  (budget_exhausted, twice)
    ACGL 2026-04-28   39,218 chars   passed

**Thirty-five characters apart**, same company, same filing type, adjacent quarters,
opposite outcomes. Nothing else in the corpus separates content from size so cleanly.

ALLY is deliberately NOT the primary case: it is the one failure that is its own
company's largest document, so the sibling comparison has no sibling. It is a case to
explain once the mechanism is known, not the case to design around.

WHAT THE RESULT DECIDES

- **The failure's reasoning is redundant and the sibling's is not** — degeneration on
  that content. The remedy is the ADR 0021 penalty ladder at the analyst, and it is
  already written down there as a conditional.
- **Both look alike** — not degeneration. A larger budget is then the honest remedy,
  as a freeze amendment with the completed items re-run or reported as a stratum.
- **Neither** — recorded as such. "Cannot tell" stays a permitted answer.

WHY IT REPLAYS RATHER THAN READS

The failing call raised before the trace was written, so its reasoning was never
recorded; the fix landed afterwards (finding #27 era). Intake's output *is* recorded for
both items, so the analyst prompt is rebuilt from it deterministically and re-issued.
Nothing here writes to the ledger, the cache, or the corpus.
"""

from __future__ import annotations

import json
import pathlib
import sys
from datetime import date

from mapf.bootstrap import build_llm_provider
from mapf.core.errors import ModelBudgetExhaustedError
from mapf.core.models import TrustedText, UntrustedText
from mapf.core.ports import SamplingParams
from mapf.core.quarantine import quarantine
from mapf.prompts.loader import FilePromptStore
from mapf.settings import ModelRegistry, load

# The pair. Failure first, so the comparison reads in the order it is argued.
PAIR = (("ACGL", date(2026, 2, 9), "FAILED"), ("ACGL", date(2026, 4, 28), "passed"))
SECONDARY = (("WH", date(2026, 4, 29), "FAILED"), ("WH", date(2026, 7, 22), "passed"))


def _intake_output(runs: pathlib.Path, ticker: str, filing: date) -> str | None:
    """What intake produced for this item, from whichever trace holds it."""
    for trace in sorted(runs.glob("*/trace.jsonl")):
        events = []
        for line in trace.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        texts = [
            m.get("content", "") for e in events for m in (e.get("data") or {}).get("messages", [])
        ]
        if not any(ticker in t and filing.isoformat() in t for t in texts):
            continue
        for event in reversed(events):
            data = event.get("data") or {}
            if event.get("stage") == "intake" and data.get("response"):
                return str(data["response"])
    return None


def _redundancy(text: str) -> tuple[int, int, float]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    unique = len(set(lines))
    return len(lines), unique, 100 * (1 - unique / len(lines)) if lines else 0.0


def main() -> int:
    settings = load()
    registry = ModelRegistry(settings.models)
    spec = registry.spec("analyst")
    provider = build_llm_provider(settings, cached=False)  # never replay our own answer
    model = registry.resolve("analyst", provider.list_models())
    prompts = FilePromptStore()
    runs = settings.paths.runs_dir

    pairs = list(PAIR) + (list(SECONDARY) if "--with-wh" in sys.argv else [])
    print(f"{'item':22}{'outcome':9}{'reasoning':>11}{'lines':>7}{'uniq':>6}{'redundant':>11}")
    for ticker, filing, outcome in pairs:
        facts = _intake_output(runs, ticker, filing)
        if facts is None:
            print(f"{ticker} {filing}   no recorded intake output; cannot rebuild the prompt")
            continue
        prompt = prompts.render(
            "scenario_analyst",
            settings.prompts.analyst,
            trusted={
                "ticker": TrustedText(ticker),
                "as_of_date": TrustedText(filing.isoformat()),
                "horizon_days": TrustedText("5"),
            },
            untrusted={"facts": quarantine(str(UntrustedText(facts)))},
        )
        try:
            response = provider.complete(
                model=model, prompt=prompt, sampling=SamplingParams(**spec.sampling.model_dump())
            )
            reasoning = response.reasoning_text or ""
            tokens = response.reasoning_tokens or 0
        except ModelBudgetExhaustedError as error:
            reasoning, tokens = error.reasoning_text, error.reasoning_tokens
        n, uniq, pct = _redundancy(reasoning)
        label = f"{ticker} {filing}"
        print(f"{label:22}{outcome:9}{tokens:>11,}{n:>7}{uniq:>6}{pct:>10.1f}%")

    print(
        "\nRead it as: the failure redundant and the sibling not -> degeneration, and the "
        "\nADR 0021 penalty ladder applies at the analyst. Both alike -> not degeneration, "
        "\nand a larger budget is the honest remedy. Neither -> cannot tell, recorded as such."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
