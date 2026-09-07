"""The four-arm ablation of git note record 17.

Arms A/B run the ordinary pipeline. Arms C/D run it with a PASS-THROUGH analyst --
an object satisfying the analyst's interface that wraps intake's facts as the
narrative and makes no model call -- so `execute` is untouched and artifact writing,
the truncation refusal and forecast assembly are identical across all four arms.

Outputs go to `var/ablation/<arm>/`, never `runs/`: these are not corpus artifacts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import typer

from mapf.agents.analyst import AnalystRequest
from mapf.bootstrap import (
    build_http_client,
    build_llm_provider,
    build_market_data,
    build_run,
)
from mapf.cli.commands.corpus import _accessions
from mapf.core.errors import MapError
from mapf.core.models import Document, EarningsFiling, ScenarioNarrative
from mapf.core.ports import ModelInfo
from mapf.core.truncation import truncate
from mapf.corpus.forecasts import load_band
from mapf.corpus.ledger import Ledger
from mapf.corpus.runner import EXECUTION_SEED
from mapf.corpus.selection import Corpus
from mapf.data.exhibits import EdgarExhibits
from mapf.data.symbols import Throttle
from mapf.pipeline.run import Agents, RunRequest, execute
from mapf.prompts.loader import FilePromptStore
from mapf.settings import ModelRegistry, load

OUT = Path("var/ablation")
FROZEN = Path("corpus/frozen.json")
INTAKE_BUDGET = 29_920
NO_ANALYST_TEMPLATE = ("structuralist_noanalyst", "v1")


class PassThroughAnalyst:
    """The analyst's interface, without the analyst.

    Record 17: arms C and D remove the agent, not the pipeline. Wrapping intake's
    facts as the narrative keeps `execute` identical across every arm, so no arm
    differs because it took a different code path.
    """

    stage = "analyst"

    def __init__(self, sampling: object) -> None:
        # The manifest must not name a model that never ran. Recording the real
        # analyst here would assert an inference that did not happen -- the exact
        # shape of Findings #39's sixth instance, committed on purpose.
        self.model = ModelInfo(
            id="none (arm C/D: analyst removed)",
            fingerprint="none",
            fingerprint_source="tag",
            fingerprint_fields=(),
        )
        self.sampling = sampling

    def run(self, request: AnalystRequest) -> ScenarioNarrative:
        return ScenarioNarrative(
            ticker=request.ticker,
            horizon_days=request.horizon_days,
            text="\n".join(str(f) for f in request.facts.facts),
            source_doc_ids=request.facts.source_doc_ids,
        )


@dataclass(frozen=True)
class Arm:
    name: str
    analyst: str  # "full" | "capped" | "none"
    structuralist: str  # "intake" | "analyst"  -- which model alias to use
    max_tokens: int | None = None


ARMS = {
    "A": Arm("A", analyst="full", structuralist="structuralist"),
    "B": Arm("B", analyst="capped", structuralist="structuralist", max_tokens=1000),
    "C": Arm("C", analyst="none", structuralist="structuralist"),
    "D": Arm("D", analyst="none", structuralist="analyst"),
    # DIAGNOSTIC ONLY (git note record 22). Ten items at the largest budget the
    # 16,384 window allows. It does not become arm D and enters no comparison.
    "probe": Arm("probe", analyst="none", structuralist="analyst", max_tokens=15000),
    "control": Arm("control", analyst="full", structuralist="structuralist"),
}


def sample(pooled: bool = True) -> list[tuple[str, object]]:
    record = json.loads(FROZEN.read_text(encoding="utf-8"))
    corpus = Corpus.model_validate(record["corpus"])
    led = Ledger(Path("var/corpus/ledger.jsonl"))
    out = []
    for band in ("clean", "ambiguous"):
        for item in load_band(led, corpus, Path("runs"), band, "dev"):
            out.append((band, item))
    return out


def main(arm: str = typer.Argument(...), limit: int = typer.Option(0)) -> None:
    spec = ARMS[arm]
    record = json.loads(FROZEN.read_text(encoding="utf-8"))
    corpus = Corpus.model_validate(record["corpus"])
    items = sample()

    if arm in ("control", "probe"):
        import numpy as np

        rng = np.random.default_rng(EXECUTION_SEED)
        keep = sorted(rng.permutation(len(items))[: 60 if arm == "control" else 10])
        items = [items[i] for i in keep]
    if limit:
        items = items[:limit]

    settings = load()
    out_dir = OUT / arm
    settings = settings.model_copy(
        update={"paths": settings.paths.model_copy(update={"runs_dir": out_dir})}
    )
    registry = ModelRegistry(settings.models)
    provider = build_llm_provider(settings, cached=(arm != "control"))
    models = registry.resolve_all(provider.list_models())
    resolved = {str(k): v for k, v in models.items()}
    by_key = {}
    for band in ("clean", "ambiguous"):
        by_key.update(_accessions(corpus, band))
    vintage = date.fromisoformat(str(record["price_vintage"]))
    prompts = FilePromptStore()

    index_path = out_dir / "index.jsonl"
    seen = set()
    if index_path.is_file():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                # Only a SUCCESSFUL run counts as done. Treating a failure as seen
                # would skip it forever on resume, which is how a transient error
                # becomes a permanent silent exclusion.
                if r.get("status") == "ok":
                    seen.add((r["ticker"], r["as_of"]))

    typer.echo(f"arm {arm}: {len(items)} items, {len(seen)} already done -> {out_dir}")
    with build_http_client(settings) as client:
        ex = EdgarExhibits(
            user_agent=settings.data.sec.user_agent,
            client=client,
            throttle=Throttle(settings.data.sec.requests_per_second),
        )
        market = build_market_data(settings)
        for n, (band, item) in enumerate(items, 1):
            f = item.forecast
            key = (f.ticker, f.as_of.date().isoformat())
            if key in seen:
                continue
            try:
                accession, cik = by_key[(f.ticker, item.entry.filing_date)]
                doc = ex.fetch(
                    EarningsFiling(accession=accession, cik=cik, filed=item.entry.filing_date)
                )
                text, trec = truncate(doc.text, budget_tokens=INTAKE_BUDGET)
                docs: tuple[Document, ...] = (
                    (doc,) if not trec.applied else (doc.model_copy(update={"text": text}),)
                )

                run_id = uuid4()
                built = build_run(settings, provider=provider, resolved=resolved, run_id=run_id)
                agents = built.agents
                if spec.analyst == "capped":
                    capped = agents.analyst.sampling.model_copy(
                        update={"max_tokens": spec.max_tokens}
                    )
                    agents = Agents(
                        intake=agents.intake,
                        analyst=agents.analyst.__class__(
                            provider=provider,
                            model=resolved["analyst"],
                            sampling=capped,
                            prompts=prompts,
                            trace=built.trace,
                            stage="analyst",
                            version=settings.prompts.analyst,
                            context_tokens=registry.spec("analyst").context_tokens,
                            upstream=registry.spec("analyst").upstream,
                            degeneration_penalty=None,
                        ),
                        structuralist=agents.structuralist,
                    )
                elif spec.analyst == "none":
                    model = resolved[
                        "analyst" if spec.structuralist == "analyst" else "structuralist"
                    ]
                    agents = Agents(
                        intake=agents.intake,
                        analyst=PassThroughAnalyst(agents.analyst.sampling),
                        structuralist=agents.structuralist.__class__(
                            provider=provider,
                            model=model,
                            # Arm D is the 12B on arm C's prompt (record 17). The
                            # structuralist's budget is None because the 4B answers
                            # directly; unbounded, the 12B reasoned for 15,406
                            # tokens and never answered. 12,000 is its registered
                            # budget everywhere else (record 19).
                            sampling=(
                                registry.spec("structuralist").sampling.model_copy(
                                    update={"max_tokens": spec.max_tokens or 12000}
                                )
                                if spec.structuralist == "analyst"
                                else registry.spec("structuralist").sampling
                            ),
                            prompts=prompts,
                            trace=built.trace,
                            stage="structuralist",
                            template=NO_ANALYST_TEMPLATE[0],
                            version=NO_ANALYST_TEMPLATE[1],
                            max_attempts=settings.inference.max_repair_attempts,
                            # The model and its window travel together. Arm D runs
                            # the 12B, whose window is 16,384; keeping the 4B's
                            # 8,192 left a negative prompt budget once the 12,000
                            # generation budget was subtracted, and the guard
                            # refused before dispatch. Same defect as the max_tokens
                            # one, one field along (record 19).
                            context_tokens=registry.spec(
                                "analyst" if spec.structuralist == "analyst" else "structuralist"
                            ).context_tokens,
                            upstream=registry.spec("structuralist").upstream,
                            degeneration_penalty=None,
                        ),
                    )

                execute(
                    RunRequest(
                        run_id=run_id,
                        ticker=f.ticker,
                        horizon_days=record["horizon_days"],
                        documents=docs,
                        history_days=settings.data.history_days,
                        as_of=datetime.combine(
                            item.entry.filing_date, datetime.min.time(), tzinfo=UTC
                        )
                        + timedelta(days=1),
                    ),
                    agents=agents,
                    market=market,
                    dividends=built.dividends,
                    trace=built.trace,
                    runs_dir=out_dir,
                    today=vintage,
                    render_chart=False,
                    freeze_version=record["freeze_version"],
                )
                row = {
                    "arm": arm,
                    "band": band,
                    "ticker": f.ticker,
                    "as_of": key[1],
                    "run_id": str(run_id),
                    "status": "ok",
                }
            except MapError as err:
                row = {
                    "arm": arm,
                    "band": band,
                    "ticker": f.ticker,
                    "as_of": key[1],
                    "run_id": None,
                    "status": "failed",
                    "reason": type(err).__name__,
                    "detail": str(err)[:200],
                }
            out_dir.mkdir(parents=True, exist_ok=True)
            with index_path.open("a", encoding="utf-8") as h:
                h.write(json.dumps(row, sort_keys=True) + "\n")
            if n % 10 == 0 or row["status"] == "failed":
                typer.echo(f"  [{n}/{len(items)}] {f.ticker} {key[1]} {row['status']}")
    typer.echo(f"arm {arm}: done")


if __name__ == "__main__":
    typer.run(main)
