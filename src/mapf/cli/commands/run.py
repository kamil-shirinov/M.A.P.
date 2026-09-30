"""`map run` — the whole pipeline, once."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import typer

from mapf.bootstrap import (
    build_exhibits,
    build_filings,
    build_http_client,
    build_llm_provider,
    build_run,
)
from mapf.cli.base import app, as_shown, fail, handle
from mapf.core.errors import MapError
from mapf.core.hashing import new_run_id
from mapf.core.models import Document
from mapf.core.tokens import AgentBudget
from mapf.core.truncation import truncate
from mapf.data.news import load_corpus
from mapf.pipeline.run import RunRequest, execute
from mapf.settings import ModelRegistry, load


@app.command()
def run(
    ticker: str = typer.Argument(..., help="Ticker to forecast, e.g. AAPL."),
    horizon: int = typer.Option(
        5, "--horizon", help="Forecast horizon in trading days (ADR 0016)."
    ),
    news_dir: Path | None = typer.Option(None, help="Override the configured news directory."),
    from_edgar: bool = typer.Option(
        False,
        "--from-edgar",
        help=(
            "Forecast from the filer's most recent 8-K Item 2.02 exhibit, discovered "
            "at runtime, instead of a news directory. The run is OUTSIDE the frozen "
            "corpus: unscored, no band, and recorded as such in its manifest."
        ),
    ),
    edgar_days: int = typer.Option(
        120,
        "--edgar-days",
        help="How far back --from-edgar searches for an Item 2.02 filing.",
    ),
    fixtures: Path | None = typer.Option(
        None, help="Replay recorded LLM fixtures instead of calling a server."
    ),
    record_to: Path | None = typer.Option(
        None,
        "--record-to",
        help=(
            "Record every LLM exchange to this directory as replayable fixtures. "
            "The destination is mandatory: a production command must never write "
            "into tests/fixtures/ on its own."
        ),
    ),
    config: Path | None = typer.Option(None, help="Config file to use instead of the default."),
) -> None:
    """Produce a validated forecast, a trace, a manifest and a chart."""
    try:
        settings = load([config] if config else None)
        if not 1 <= horizon <= 252:
            raise fail(f"--horizon must be between 1 and 252, got {horizon}", 2)

        if from_edgar and news_dir is not None:
            raise fail("--from-edgar and --news-dir are different document sources", 2)
        if edgar_days < 1:
            # Otherwise the window runs backwards and the failure below reports an
            # interval nobody asked for, as if EDGAR had nothing to offer.
            raise fail(f"--edgar-days must be at least 1, got {edgar_days}", 2)

        source: Literal["edgar", "news"] = "edgar" if from_edgar else "news"
        if from_edgar:
            end = datetime.now(UTC).date()
            start = end - timedelta(days=edgar_days)
            with build_http_client(settings) as client:
                filings = build_filings(settings, client).earnings_filings(ticker, start, end)
                if not filings:
                    # NEVER fall back to the news path. The two answer different
                    # questions, and a silent substitution would produce a forecast
                    # from unrelated documents under a flag that says otherwise.
                    raise fail(
                        f"no 8-K Item 2.02 filing for {ticker} between {start} and {end}",
                        5,
                        hint=(
                            f"Searched {edgar_days} days. Widen it with --edgar-days, "
                            "or drop --from-edgar to forecast from news instead. This "
                            "does not fall back on its own."
                        ),
                    )
                latest = filings[-1]
                document = build_exhibits(settings, client).fetch(latest)
            # The same intake budget the corpus path cuts to, so an EDGAR run and a
            # corpus run of the same exhibit see the same document.
            intake = ModelRegistry(settings.models).spec("intake")
            text, record = truncate(
                document.text,
                budget_tokens=AgentBudget(
                    agent="intake",
                    context_tokens=intake.context_tokens,
                    max_tokens=intake.sampling.max_tokens,
                ).document_budget,
            )
            # The id still hashes the bytes EDGAR served (ADR 0005); truncation is
            # recorded beside the hash, never folded into it.
            if record.applied:
                document = document.model_copy(update={"text": text})
            documents: tuple[Document, ...] = (document,)
            typer.secho(
                f"edgar      {latest.accession} filed {latest.filed}"
                + (f" — {record.describe()}" if record.applied else ""),
                fg=typer.colors.GREEN,
            )
        else:
            corpus_dir = news_dir or settings.news.dir
            with build_http_client(settings) as client:
                documents = load_corpus(
                    corpus_dir,
                    settings.news.rss_urls,
                    client=client if settings.news.rss_urls else None,
                )
            if not documents:
                raise fail(
                    f"no news found in {corpus_dir}",
                    5,
                    hint=(
                        "Put .txt or .md files there, or set news.rss_urls in "
                        "config/default.toml. A forecast needs something to reason from."
                    ),
                )

        provider = build_llm_provider(settings, fixtures=fixtures)
        if record_to is not None:
            from mapf.providers.fake import RecordingProvider

            provider = RecordingProvider(provider, record_to)

        registry = ModelRegistry(settings.models)
        resolved = {str(k): v for k, v in registry.resolve_all(provider.list_models()).items()}

        run_id = new_run_id()
        wiring = build_run(settings, provider=provider, resolved=resolved, run_id=run_id)
        result = execute(
            RunRequest(
                ticker=ticker,
                horizon_days=horizon,
                documents=documents,
                history_days=settings.data.history_days,
                run_id=run_id,
                as_of=datetime.now(UTC),
            ),
            agents=wiring.agents,
            market=wiring.market,
            dividends=wiring.dividends,
            trace=wiring.trace,
            runs_dir=wiring.runs_dir,
            allow_nondeterministic=wiring.allow_nondeterministic,
            # Positively recorded, not inferred from a missing freeze_version:
            # this run is outside the frozen corpus and must never be pooled with
            # corpus items.
            document_source=source,
        )

        typer.secho(f"run {run_id}", fg=typer.colors.GREEN)
        typer.echo(
            f"  spot        {result.forecast.spot_price:.2f} "
            f"({result.window.provider}, {result.window.adjustment})"
        )
        for label in ("bullish", "base_case", "bearish"):
            scenario = getattr(result.forecast.scenarios, label)
            typer.echo(
                f"  {label:11} p={scenario.probability_weight:.2f}  "
                # Stored as a fraction; multiplied here for human display only.
                f"{as_shown(scenario.price_return * 100)}%  "
                f"vol={scenario.annualised_vol:.4g}"
            )
        if not result.manifest.dividends.known:
            typer.secho(
                "  note: ex-dividend dates in the forecast window are unknown; "
                "Phase 2 must not read that as 'none' (ADR 0013).",
                fg=typer.colors.YELLOW,
            )
        elif result.manifest.dividends.ex_dates:
            typer.secho(
                f"  note: {len(result.manifest.dividends.ex_dates)} ex-dividend date(s) "
                f"in the window, total {result.manifest.dividends.total_amount:.4f}. "
                "A split-adjusted series keeps that drop (ADR 0013).",
                fg=typer.colors.YELLOW,
            )
        typer.echo(f"  artifacts   {result.run_dir}")
    except MapError as err:
        raise handle(err) from err
