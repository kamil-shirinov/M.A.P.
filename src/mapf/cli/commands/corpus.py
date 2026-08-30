"""`map corpus` — execute the frozen corpus, or pre-flight it without inference.

Twelve nights of compute rest on things that are cheap to check and expensive to
discover: that the live prompts still match the frozen hashes, that the server has
the right models, that every exhibit still fetches to the byte it did when the
corpus was frozen. `--check` runs all of it and exits.

Resume is automatic rather than a flag. A job restarted at 2am must not depend on
remembering an argument — but what it skips is reported explicitly, so an
unintended resume is visible rather than silent.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from uuid import UUID

import typer

from mapf.bootstrap import build_http_client, build_llm_provider, build_run
from mapf.cli.app import app, fail, handle
from mapf.core.errors import ExhibitError, MapError
from mapf.core.models import Document, EarningsFiling
from mapf.core.tokens import AgentBudget, check_fit, estimate_tokens
from mapf.core.truncation import plan_truncation, truncate
from mapf.corpus.ledger import Ledger, LedgerEntry, is_terminal
from mapf.corpus.runner import (
    TRUNCATION_NOTES,
    CorpusHaltedError,
    CorpusItem,
    Health,
    RunnerConfig,
    plan,
    run_band,
    verify_freeze,
)
from mapf.corpus.selection import Corpus
from mapf.data.exhibits import EdgarExhibits
from mapf.data.symbols import Throttle
from mapf.pipeline.context_probe import probe_context
from mapf.prompts.loader import FilePromptStore
from mapf.settings import ModelRegistry, load
from mapf.settings.loader import Settings

corpus_app = typer.Typer(help="Run or pre-flight the frozen corpus.")
app.add_typer(corpus_app, name="corpus")

FROZEN = Path("corpus/frozen.json")
LEDGER = Path("var/corpus/ledger.jsonl")


def _load_frozen(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise fail(
            f"no frozen corpus at {path}",
            5,
            hint="The corpus is the pre-registration. Freeze and commit it first.",
        )
    parsed: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return parsed


def _accessions(corpus: Corpus, band: str) -> dict[tuple[str, date], tuple[str, int]]:
    """Item key to (accession, cik). The frozen record is the only source."""
    out: dict[tuple[str, date], tuple[str, int]] = {}
    for plan_ in corpus.accepted:
        for filings in plan_.filings:
            if filings.band != band:
                continue
            for day, accession in zip(filings.dates, filings.accessions, strict=True):
                out[(plan_.ticker, day)] = (accession, plan_.cik or 0)
    return out


@corpus_app.command("run")
def corpus_run(
    band: str = typer.Option("clean", help="Which band to execute. Clean runs first."),
    check: bool = typer.Option(
        False, "--check", help="Pre-flight only: verify everything, run no inference."
    ),
    frozen: Path = typer.Option(FROZEN, help="The frozen corpus to execute."),
    ledger_path: Path = typer.Option(LEDGER, help="Where item outcomes are recorded."),
    limit: int | None = typer.Option(None, help="Stop after this many items."),
    config: Path | None = typer.Option(None, help="Config file to use instead of the default."),
) -> None:
    """Execute one band of the frozen corpus, resuming automatically."""
    try:
        settings = load([config] if config else None)
        record = _load_frozen(frozen)
        corpus = Corpus.model_validate(record["corpus"])
        prompts = FilePromptStore()

        if band not in {b.name for b in corpus.criteria.bands}:
            raise fail(
                f"unknown band {band!r}",
                2,
                hint=f"Bands in this corpus: {', '.join(b.name for b in corpus.criteria.bands)}",
            )

        items = plan(corpus, band)
        if limit is not None:
            items = items[:limit]

        # 1. The prompts, before anything expensive. A drifted template invalidates
        #    every cache key, which is the difference between a replay and twelve
        #    nights, so this refuses rather than warns.
        registry = ModelRegistry(settings.models)
        verify_freeze(
            record,
            live_digest=prompts.digest,
            live_models={
                stage: _live_spec(registry, settings, stage)
                for stage in ("intake", "analyst", "structuralist")
            },
        )
        typer.secho(
            "freeze     prompts, aliases and sampling match the frozen record",
            fg=typer.colors.GREEN,
        )

        # 2. The ledger, so a resume is announced rather than assumed.
        ledger = Ledger(ledger_path)
        resolved = ledger.resolved()
        in_band = {k: v for k, v in resolved.items() if k[1] == band}
        done = sum(1 for v in in_band.values() if v.status == "complete")
        terminal = sum(1 for v in in_band.values() if is_terminal(v.reason))
        exhausted = {k: v for k, v in ledger.exhausted().items() if k[1] == band}
        remaining = [i for i in items if i.key not in resolved]
        if in_band:
            typer.secho(
                f"resume     skipping {len(in_band)} of {len(items)} items "
                f"({done} complete, {terminal} terminal failures, "
                f"{len(exhausted)} retries exhausted) — {len(remaining)} to run",
                fg=typer.colors.YELLOW,
            )
        # Named individually, unlike the terminal failures. "This filing has no
        # exhibit" is a fact about the corpus; "we stopped asking" is a decision,
        # and a decision that removes an item from the sample should not be a count
        # (ADR 0024).
        for key, entry in sorted(exhausted.items()):
            typer.secho(
                f"           {key[0]} {key[2]}: {entry.reason} twice — not retried again",
                fg=typer.colors.YELLOW,
            )
        else:
            typer.echo(f"resume     nothing recorded; all {len(items)} items to run")

        provider = build_llm_provider(settings, cached=True)
        models = registry.resolve_all(provider.list_models())
        typer.secho(
            "models     " + ", ".join(f"{k}={v.id}" for k, v in models.items()),
            fg=typer.colors.GREEN,
        )

        vintage = date.fromisoformat(str(record["price_vintage"]))
        by_key = _accessions(corpus, band)

        with build_http_client(settings) as client:
            exhibits = EdgarExhibits(
                user_agent=settings.data.sec.user_agent,
                client=client,
                throttle=Throttle(settings.data.sec.requests_per_second),
            )

            if check:
                budgets = [
                    AgentBudget(
                        agent=stage,
                        context_tokens=registry.spec(stage).context_tokens,
                        max_tokens=registry.spec(stage).sampling.max_tokens,
                    )
                    for stage in ("intake",)
                ]
                _probe_contexts(provider, models, registry)
                _preflight(record, band, items, exhibits, by_key, vintage, budgets)
                return

            intake_budget = AgentBudget(
                agent="intake",
                context_tokens=registry.spec("intake").context_tokens,
                max_tokens=registry.spec("intake").sampling.max_tokens,
            ).document_budget

            def documents(item: CorpusItem) -> tuple[Document, ...]:
                accession, cik = by_key[(item.ticker, item.filing_date)]
                document = exhibits.fetch(
                    EarningsFiling(accession=accession, cik=cik, filed=item.filing_date)
                )
                text, record = truncate(document.text, budget_tokens=intake_budget)
                if not record.applied:
                    return (document,)
                TRUNCATION_NOTES[item.key] = record.removed_chars
                typer.secho(
                    f"           truncated {item.ticker} {item.filing_date}: {record.describe()}",
                    fg=typer.colors.YELLOW,
                )
                # The id still hashes the bytes EDGAR served (ADR 0005); truncation
                # is a processing step recorded beside the hash, not inside it.
                return (document.model_copy(update={"text": text}),)

            def wiring(run_id: UUID) -> object:
                # Per item, not per band: a shared CountingTrace reports
                # band-cumulative counters in every manifest and writes every
                # item's events into the first item's directory.
                return build_run(
                    settings,
                    provider=provider,
                    resolved={str(k): v for k, v in models.items()},
                    run_id=run_id,
                )

            typer.echo(
                f"start      band={band} items={len(remaining)} vintage={vintage} charts=off"
            )
            health = run_band(
                items,
                documents=documents,
                wiring=wiring,  # type: ignore[arg-type]
                ledger=ledger,
                config=RunnerConfig(
                    runs_dir=settings.paths.runs_dir,
                    price_vintage=vintage,
                    freeze_version=_freeze_version(record),
                ),
                on_progress=_progress,
            )

        typer.secho(
            f"done       {health.completed} complete, {health.failed} failed, "
            f"fidelity_ok={health.fidelity_ok}",
            fg=typer.colors.GREEN,
        )
    except CorpusHaltedError as error:
        typer.secho(f"HALTED     {error}", fg=typer.colors.RED, err=True)
        typer.secho(
            "           the corpus is incomplete by decision, not by accident. "
            "Diagnose before resuming.",
            err=True,
        )
        raise typer.Exit(7) from error
    except MapError as error:
        raise handle(error) from error


def _freeze_version(record: Mapping[str, object]) -> str | None:
    """The frozen record's own version, for stamping into every manifest.

    Absent rather than fabricated when the record does not carry one: a run that
    genuinely does not know its freeze must not claim a version it invented.
    """
    value = record.get("freeze_version")
    return str(value) if isinstance(value, str) and value else None


def _live_spec(registry: ModelRegistry, settings: Settings, stage: str) -> dict[str, object]:
    """Every configured value the freeze might record, for comparison against it.

    Assembled here rather than read from the frozen record so a field the freeze
    names but the config no longer has is a mismatch rather than an omission.
    """
    spec = registry.spec(stage)  # type: ignore[arg-type]
    configured = getattr(settings.models, stage)
    return {
        "alias": spec.alias,
        "temperature": spec.sampling.temperature,
        "max_tokens": spec.sampling.max_tokens,
        "context_tokens": spec.context_tokens,
        "max_visible_tokens": configured.max_visible_tokens,
        "degeneration_penalty": spec.degeneration_penalty,
    }


def _progress(index: int, total: int, item: CorpusItem, entry: LedgerEntry, health: Health) -> None:
    """One line per item. This is what gets watched for twelve nights."""
    ok = entry.status == "complete"
    outcome = "ok" if ok else f"FAIL:{entry.reason}"
    if entry.degeneration_retry:
        typer.secho(
            f"           NOTE {item.ticker} {item.filing_date}: "
            f"{entry.retried_agents} looped at its cap and was re-run once under a "
            f"frequency penalty — this item is in the sensitivity partition",
            fg=typer.colors.YELLOW,
        )
    if entry.output_truncated:
        typer.secho(
            f"           WARNING {item.ticker} {item.filing_date}: "
            f"{entry.truncated_agents} stopped at its token cap rather than "
            f"finishing — downstream reasoned from a fragment",
            fg=typer.colors.YELLOW,
        )
    typer.secho(
        f"[{index:>4}/{total}] {item.ticker:<6} {item.band:<9} {item.filing_date} "
        f"{entry.elapsed_s:>6.1f}s  {outcome:<24}"
        f"done={health.completed} fail={health.failed} "
        f"unparse={health.unparseable} diverge={health.divergent} "
        f"ungrounded={health.ungrounded_numerals} flat={health.degenerate_spread} "
        f"exhausted={health.budget_exhausted} cutoff={health.output_truncated} "
        f"retried={health.degeneration_retry}",
        fg=typer.colors.GREEN if ok else typer.colors.RED,
    )


def _probe_contexts(provider: object, models: object, registry: object) -> None:
    """Ask the server for its real context window, per agent.

    A configured number the server does not honour is exactly how the first run
    failed, so this compares against reality rather than against `config`.
    """
    disagreements: list[str] = []
    for stage in ("intake", "analyst", "structuralist"):
        spec = registry.spec(stage)  # type: ignore[attr-defined]
        report = probe_context(
            provider,  # type: ignore[arg-type]
            models[stage],  # type: ignore[index]
            agent=stage,
            configured=spec.context_tokens,
        )
        colour = typer.colors.GREEN if report.agrees else typer.colors.RED
        typer.secho(f"context    {report.describe()}", fg=colour)
        if not report.agrees:
            disagreements.append(report.describe())
    if disagreements:
        raise fail(
            "the server's context windows do not match the configuration",
            2,
            hint=(
                "config/default.toml is what the corpus was sized against; the "
                "inference server is what will actually run it. Raise the context "
                "where the model is loaded, or lower it in config and re-check "
                "which exhibits still fit."
            ),
        )


def _preflight(
    record: dict[str, object],
    band: str,
    items: tuple[CorpusItem, ...],
    exhibits: EdgarExhibits,
    by_key: dict[tuple[str, date], tuple[str, int]],
    vintage: date,
    budgets: list[AgentBudget] | None = None,
) -> None:
    """Re-hash every exhibit against the frozen record and report. No inference."""
    frozen_hashes = record.get("exhibits")
    known: dict[str, dict[str, object]] = {}
    if isinstance(frozen_hashes, dict):
        raw = frozen_hashes.get("by_accession")
        if isinstance(raw, dict):
            known = raw

    typer.echo(f"exhibits   re-hashing {len(items)} items against the frozen record")
    missing: list[str] = []
    changed: list[str] = []
    unrecorded: list[str] = []
    for n, item in enumerate(items, 1):
        accession, cik = by_key[(item.ticker, item.filing_date)]
        try:
            document = exhibits.fetch(
                EarningsFiling(accession=accession, cik=cik, filed=item.filing_date)
            )
        except ExhibitError:
            missing.append(f"{item.ticker} {item.filing_date} {accession}")
            continue
        expected = known.get(accession, {}).get("document_id")
        if expected is None:
            unrecorded.append(accession)
        elif expected != document.id:
            changed.append(f"{item.ticker} {item.filing_date} {accession}")
        if n % 50 == 0:
            typer.echo(f"           {n}/{len(items)}")

    if budgets:
        _report_fit(record, items, by_key, budgets)
    typer.echo(f"vintage    {vintage} (pinned)")
    for label, rows, colour in (
        ("unfetchable", missing, typer.colors.RED),
        ("content changed", changed, typer.colors.RED),
        ("not in frozen record", unrecorded, typer.colors.YELLOW),
    ):
        if rows:
            typer.secho(f"{label:<11}{len(rows)}", fg=colour)
            for row in rows[:10]:
                typer.echo(f"           {row}")
    if not missing and not changed and not unrecorded:
        typer.secho(f"exhibits   all {len(items)} match the frozen hashes", fg=typer.colors.GREEN)
    typer.secho("check      pre-flight complete; no inference ran", fg=typer.colors.GREEN)
    if missing or changed:
        raise typer.Exit(6)


def _report_fit(
    record: dict[str, object],
    items: tuple[CorpusItem, ...],
    by_key: dict[tuple[str, date], tuple[str, int]],
    budgets: list[AgentBudget],
) -> None:
    """Whether every exhibit fits, and which agent binds when one does not.

    Sizes come from the frozen record, so this costs nothing and can run before the
    exhibits are fetched at all. Reporting the binding agent turns "it will not
    fit" into "raise this one number".
    """
    frozen = record.get("exhibits")
    sizes: dict[str, int] = {}
    if isinstance(frozen, dict):
        raw = frozen.get("by_accession")
        if isinstance(raw, dict):
            sizes = {a: int(v.get("chars", 0)) for a, v in raw.items()}

    tight = max(b.document_budget for b in budgets)
    typer.echo(
        f"tokens     budget {tight:,} tokens per document "
        f"(binding agent: {min(budgets, key=lambda b: b.document_budget).agent})"
    )
    over: list[tuple[str, int, int]] = []
    truncated: list[tuple[str, int]] = []
    for item in items:
        accession, _ = by_key[(item.ticker, item.filing_date)]
        chars = sizes.get(accession)
        if not chars:
            continue
        result = check_fit(estimate_tokens(chars), budgets)
        if result.fits:
            continue
        # The rule is what makes an oversized exhibit runnable, so the gate asks
        # whether it fits AFTER truncation. Refusing here would refuse items the
        # pipeline handles.
        cut = plan_truncation(chars, budget_tokens=tight)
        if cut.applied and cut.estimated_tokens <= tight:
            truncated.append((f"{item.ticker} {item.filing_date}", cut.removed_chars))
            continue
        over.append((f"{item.ticker} {item.filing_date}", result.tokens, -result.headroom))

    if truncated:
        typer.secho(
            f"tokens     {len(truncated)} exhibits will be truncated by the frozen rule (ADR 0020)",
            fg=typer.colors.YELLOW,
        )
        for label, removed in sorted(truncated, key=lambda r: -r[1])[:15]:
            typer.echo(f"           {label:<22}{removed:,} chars elided")

    if not over:
        typer.secho(
            f"tokens     all {len(items)} exhibits fit "
            f"({len(items) - len(truncated)} whole, {len(truncated)} truncated)",
            fg=typer.colors.GREEN,
        )
        return
    typer.secho(
        f"tokens     {len(over)} of {len(items)} exhibits exceed the budget",
        fg=typer.colors.RED,
    )
    for label, tokens, excess in sorted(over, key=lambda r: -r[1])[:15]:
        typer.echo(f"           {label:<22}~{tokens:>7,} tokens, over by {excess:,}")
    raise fail(
        f"{len(over)} exhibits cannot fit the configured context",
        6,
        hint=(
            "Raise the binding agent's context_tokens and reload the model on the "
            "inference server, "
            "or apply the frozen truncation rule (ADR 0020). This is a pre-flight "
            "result, not a run-time failure."
        ),
    )
